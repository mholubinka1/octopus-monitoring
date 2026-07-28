# Fix consumption UTC storage and local-day cost/consumption bucketing

## Problem Statement

Daily cost figures computed from the database don't match Octopus's own reported values, for reasons that have nothing to do with pricing, VAT, or rounding. Live investigation against the production database and Octopus's live consumption/rate APIs (20–26 July) traced this to two compounding bugs:

1. **Wrong rate per half-hour.** Octopus's consumption endpoint returns `interval_start`/`interval_end` as local British time with an explicit UTC offset (`+01:00` during BST). `ConsumptionClient.get_consumption_directly_from_endpoint` (`app/data/octopus/consumption.py`) passes these straight through into `Consumption.start`/`.end`, and `MariaDBClient.write_consumption` (`app/data/mysql/client.py`) persists them directly into a naive `DATETIME` column — silently dropping the offset instead of converting to UTC first. During BST, every stored `consumption.period_from`/`period_to` ends up exactly 1 hour ahead of the true UTC instant. Since `product_rate` *is* stored correctly in UTC (Octopus's rate endpoints already return UTC), joining consumption to `product_rate` on this mislabeled timestamp attributes each half-hour's usage to the *wrong* half-hour's Agile rate — producing a cost error with no fixed size or sign (it depends on how much the true and mislabeled rates happen to differ that day).
2. **Wrong day boundary.** Every place that groups by calendar day (`DATE(c.period_from)` in `app/data/mysql/client.py` and throughout `grafana/mariadb/queries.md`) currently groups by the raw UTC date. Octopus's own daily reporting — and a UK user's own sense of "cost for 26 July" — means the **local (Europe/London) calendar day**, which during BST starts and ends 1 hour earlier in UTC terms. Fixing bug 1 without also fixing this would silently swap one day-boundary bug for another.

Manual proof: recomputing 20–26 July's daily cost using (a) the correct UTC instant for each half-hour's rate lookup, and (b) local-day grouping, reproduced Octopus's official app figures exactly for all 7 days. Using UTC-day grouping alone (fixing bug 1 only) left a residual, smaller mismatch on most of the same days.

## Solution

- Convert `interval_start`/`interval_end` to true UTC immediately on ingest, before they reach `Consumption.start`/`.end`, so `consumption.period_from`/`period_to` are always correct UTC regardless of season (BST or GMT).
- Bucket every "day" calculation — cost-per-day, consumption-per-day, hour-of-day — by the Europe/London local calendar day, not the raw UTC date, consistently across the app and the Grafana reference queries.
- Extend the existing day-completeness guard (48 half-hourly rows = a complete day) to account for the two UK clock-change dates each year, which are 46 (spring-forward) or 50 (fall-back) rows in local time, not 24 hours.
- No automated migration of historical raw `consumption` data — the user will manually clear the table and let the existing Startup Backfill repopulate it once the fixed image is deployed, since raw retention is already bounded to 45 days. `daily_consumption_summary` needs no data correction (its historical totals are already right — see Further Notes) — only its populating query's bucketing logic needs to change to stay correct going forward.

## User Stories

1. As the account holder, I want the database's computed daily cost to match what Octopus's own app reports for the same day, so that I can trust the Grafana dashboard and the app's own cost-forecast figures instead of a number that's silently wrong by an unpredictable amount.
2. As the account holder, I want this to hold correctly year-round, not just during BST, so that the fix doesn't need revisiting every time the clocks change.
3. As a future maintainer, I want `consumption.period_from`/`period_to` to always be true UTC in storage, matching every other timestamp column in the schema (`agreement`, `product_rate`), so nothing downstream has to guess which columns need timezone handling.
4. As a future maintainer, I want one shared, tested definition of "which local day does this UTC instant fall on" and "how many half-hourly slots does that local day have," so the two clock-change days a year are handled consistently everywhere rather than each call site reinventing (or missing) the logic.
5. As the account holder, I want the weekly consumption-summarization job and the one-time yearly-comparison backfill to use the same day-bucketing convention, so `daily_consumption_summary` never has two different day boundaries silently disagreeing depending on which job last wrote a given date.
6. As the account holder, I want the Grafana panels that break consumption/cost down by day or hour (Yesterday's Cost, Daily Average Cost/Usage, Day-of-Week Average, the Hour×Day heatmap, Gas panels) to reflect local time, so the dashboard matches how I actually experience "my day."

## Implementation Decisions

- **`app/data/octopus/consumption.py`**: in `get_consumption_directly_from_endpoint`, convert each `reading.interval_start`/`interval_end` to UTC (`.astimezone(datetime.UTC)`) before constructing `Consumption(start=..., end=...)`. This is season-agnostic — during GMT the offset is already 0 so the conversion is a no-op; during BST it corrects the 1-hour skew.
- **New module `app/data/local_day.py`**: a small, pure, dependency-free (beyond stdlib `zoneinfo`) module shared by every day-bucketing call site:
  - `to_local_date(instant: datetime) -> date` — converts a UTC-aware or UTC-naive-assumed datetime to its Europe/London calendar date.
  - `expected_half_hour_count(local_date: date) -> int` — returns 48 for a normal day, 46 for the UK spring-forward date, 50 for the UK fall-back date that year, computed from `zoneinfo` DST transition data (not a hardcoded date table).
- **`app/data/mysql/client.py`**:
  - `read_elapsed_billing_period_costs`: fetch the joined half-hourly rows (as today), then group into daily totals in Python using `local_day.to_local_date`, and apply the completeness guard using `local_day.expected_half_hour_count` per day instead of a hardcoded `== 48`.
  - `read_consumption_summarization_window`: same change — group raw `consumption` rows by local day in Python rather than `func.date(period_from)` in SQL, so this stays consistent with `ConsumptionSummaryBackfill` (which already buckets correctly, since it reads `point.start.date()` directly off Octopus's still-locally-offset API response before any DB round-trip).
  - Both queries currently aggregate in SQL (`SUM`/`MAX`/`GROUP BY`); moving day-bucketing to Python means fetching the underlying joined/raw rows instead and aggregating them in the client method body. Data volumes stay small (raw retention is 45 days; a billing period is at most ~1 month), so this is not a performance concern.
- **`grafana/mariadb/queries.md`**: wrap every grouping/labeling expression that currently reads `period_from` directly — `DATE(...)`, `HOUR(...)`, `DAYNAME(...)` — in `CONVERT_TZ(period_from, 'UTC', 'Europe/London')` first. Confirmed live against the production database that `CONVERT_TZ` with named zones works (MariaDB's zone tables are loaded). Update the file's standing conventions note (next to "Schema assumed") to document this alongside the existing half-open-window convention.
- **Day-completeness guard**: every site currently checking `COUNT(*) == 48` (or equivalent) for a strictly-past day switches to comparing against `local_day.expected_half_hour_count(that_day)`.
- **No schema changes.** Column types and table shapes are unchanged — this is purely a fix to what values get written and how they're grouped.
- **No changes to `ConsumptionSummaryBackfill`** — it already buckets correctly today (see Further Notes) and is out of scope.
- See [ADR-0010](../adr/0010-local-day-bucketing-python-vs-sql.md) for why app-side bucketing is Python/`zoneinfo`-based rather than SQL `CONVERT_TZ`, and the `Local Day`/`Day Completeness` terms in `.agent-docs/context.md`.

## Testing Decisions

- **Ingestion UTC fix**: extend `tests/test_consumption_seam.py`'s existing `responses`-mocked seam (`OctopusEnergyAPIClient.get_consumption_directly_from_endpoint` → `MariaDBClient.write_consumption` → query `model.consumption`) with a fixture using a `+01:00`-offset `interval_start`/`interval_end`, asserting the stored `period_from`/`period_to` and derived `id` reflect the correctly UTC-shifted instant. Keep the existing `+00:00` case passing unchanged (it's already a no-op case for the fix).
- **`local_day.py`**: new `tests/test_local_day.py`, pure unit tests with no DB — cover a normal mid-year date, a UTC-midnight-crossing instant (e.g. 23:30 UTC during BST falls on the *next* local day), the exact spring-forward and fall-back dates (46 and 50 respectively), and the days immediately either side of each (still 48).
- **`read_elapsed_billing_period_costs`**: extend `tests/test_elapsed_billing_period_costs.py` with a case where consumption spans a UTC-midnight boundary that isn't a local-midnight boundary (proving grouping is local-day, not UTC-day), and a case on/around a clock-change date proving the completeness guard now expects 46/50 rather than 48.
- **`read_consumption_summarization_window`**: extend `tests/test_consumption_summarization.py` the same way, plus a case asserting its output is consistent with what `ConsumptionSummaryBackfill` would have produced for the same underlying data (same local-day boundary), to directly test the consistency concern that motivated this fix.
- **Grafana `queries.md`**: no automated test, consistent with this file's existing convention (a documentation file with no test harness) — see `bugfix-grafana-query-half-open-window.md`'s testing decisions for precedent. Acceptance check is manual: after deployment and the DB wipe/repopulate, re-run the corrected queries against production and confirm they match Octopus's official values, the same way the investigation's proof-of-concept did.
- Maintain the project's 80% coverage bar; these are all business-logic-bearing changes (timestamp correctness, day-boundary correctness) so should be fully covered by the above rather than relying on incidental coverage from other tests.

## Out of Scope

- Any automated migration or backfill of historical raw `consumption` rows. The user will manually clear the table and redeploy; the existing Startup Backfill (already re-runs in full on every process start, bounded by `retention_days`) repopulates it correctly under the fixed code.
- Any correction to `daily_consumption_summary`'s existing stored data — it's already correct (see Further Notes).
- Any change to `ConsumptionSummaryBackfill` — already buckets by local day correctly, untouched by this fix.
- Reopening issue #434 — this is root-caused as a distinct bug (timezone mislabeling + day-boundary convention) from #434's join-fan-out bug, tracked as fresh issue(s) instead, referencing #434 for context only.
- Any change to VAT handling, standing-charge logic, or the Agile rate join's half-open-window logic itself (`c.period_from >= valid_from AND c.period_from < valid_to`) — all already correct; only the value fed into that join and the day it gets bucketed into are wrong today.
- Any dashboard/UI change beyond the SQL text in `queries.md` (no new panels, no provisioning).

## Further Notes

- `daily_consumption_summary`'s existing historical data needs no correction: its kWh-per-day totals already match Octopus's own figures, because day-bucketing on the *mislabeled* (BST-as-UTC) timestamp happens to reproduce the correct local calendar day by accident (the mislabeled value's wall-clock digits *are* the true local time — that's the bug). Only the *rate* used per half-hour was ever wrong, which the daily consumption summary never involved (it's kWh-only, no rate join). This also explains why `ConsumptionSummaryBackfill`, which reads `point.start.date()` directly off Octopus's still-local-offset API response, has always bucketed correctly without needing this fix.
- This is a distinct bug from `bugfix-consumption-timezone-and-scheduler-backoff.md` (already shipped) — that one was about outgoing request query-string encoding causing `consumption_refresh` to fail with 400s during BST. This one is about incoming response values never being UTC-normalized before persisting. Both happen to involve BST, which is coincidental, not the same root cause.
- Found and diagnosed via live investigation against the production MariaDB and Octopus's live consumption/rate APIs (not a synthetic reproduction) — see the conversation history for the diagnostic scripts and exact numbers (7 days, 336 half-hours cross-checked against Octopus directly).

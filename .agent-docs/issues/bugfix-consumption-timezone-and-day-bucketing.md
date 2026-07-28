# Issues: bugfix-consumption-timezone-and-day-bucketing

## Shared local-day/DST helper module (#440)

**Blocked by**: None

**User stories**: 4

### What to build

A new small, pure module (`app/data/local_day.py`) providing the shared definition of "which Europe/London calendar day does this UTC instant fall on" and "how many half-hourly slots does that local day have." Two functions: one converts a UTC instant to its local calendar date; the other returns the expected half-hourly row count for a given local date — 48 normally, 46 on the UK spring-forward date, 50 on the UK fall-back date, computed from `zoneinfo` DST transition data rather than a hardcoded date table. No database or Octopus API dependency — pure functions operating on stdlib `datetime`/`date`/`zoneinfo` types.

### Acceptance criteria

- [x] Converting a UTC instant to its local date returns the correct Europe/London calendar day, including for instants that cross the UTC-midnight boundary without crossing the local-midnight boundary (and vice versa)
- [x] The expected-slot-count function returns 48 for an ordinary day
- [x] The expected-slot-count function returns 46 for the UK spring-forward date and 50 for the UK fall-back date, correctly identifying those dates for any given year via `zoneinfo`, not a hardcoded table
- [x] The days immediately before and after each clock-change date still return 48
- [x] No changes to any other module — this is a standalone addition (also added `start_of_local_day` and the `tzdata` dependency, needed by later issues)

---

## Consumption ingestion UTC normalization (#441)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Fix `ConsumptionClient.get_consumption_directly_from_endpoint` (`app/data/octopus/consumption.py`) so that `interval_start`/`interval_end` are converted to true UTC before being used to construct `Consumption.start`/`.end`. This ensures `consumption.period_from`/`period_to` are always stored as correct UTC, matching every other timestamp column in the schema, regardless of whether Octopus's response carries a `+00:00` (GMT) or `+01:00` (BST) offset.

### Acceptance criteria

- [x] A consumption reading with a `+01:00`-offset `interval_start`/`interval_end` (BST) is persisted with `period_from`/`period_to` shifted back by one hour to the correct UTC instant
- [x] A consumption reading with a `+00:00`-offset `interval_start`/`interval_end` (GMT) is persisted unchanged (this case must continue to pass — it's already correct today)
- [x] The derived consumption row `id` reflects the corrected UTC instant, not the raw offset-carrying value
- [x] No change to gas consumption's unit conversion (`to_estimated_kwh`) or any other field

---

## Elapsed billing period costs: local-day bucketing and DST-aware completeness guard (#442)

**Blocked by**: #440 (shared local-day helper)

**User stories**: 1, 4, 5

### What to build

`MariaDBClient.read_elapsed_billing_period_costs` currently groups the consumption/rate join by `func.date(period_from)` (UTC date) in SQL, and guards day-completeness with a hardcoded `COUNT(*) == 48`. Change it to fetch the joined half-hourly rows and group them into daily totals in Python using the shared local-day helper, applying the completeness guard against that day's expected slot count (48/46/50) instead of a fixed 48. The current, still-in-progress day (matching `period_to`'s local date) remains exempt from the guard, as today.

**Scope expanded during implementation**: `cost_forecast.py`'s own day-boundary arithmetic (`_midnight_utc`, the gap-fill day loop, the remaining-days window, and the Agile forecast tiling's day-grouping) had the same UTC-day assumption baked in and was fixed in the same commit — left alone, the first day of every billing period would have been wrongly miscounted as incomplete under BST. See issue comment for detail.

### Acceptance criteria

- [x] A billing period's daily costs are grouped by Europe/London local calendar day, not UTC date
- [x] A case where consumption spans a UTC-midnight boundary that is not a local-midnight boundary (e.g. late-evening BST consumption sitting just before UTC midnight but on the same local day) is grouped into the correct single local day, not split across two
- [x] A strictly-past day on the UK spring-forward date with exactly 46 half-hourly rows is treated as complete (previously would have been wrongly excluded under a hardcoded 48 check)
- [x] A strictly-past day on the UK fall-back date with exactly 50 half-hourly rows is treated as complete
- [x] Days immediately either side of a clock-change date still require 48 rows to count as complete
- [x] All existing tests in `tests/test_elapsed_billing_period_costs.py` continue to pass (region scoping, mid-period rate changes, incomplete-day exclusion, current-day exemption)
- [x] (Added) `cost_forecast.py`'s day-boundary arithmetic uses the same local-day helpers; all of `test_cost_forecast_retriever.py` and `test_cost_forecast_agreement_selection.py` continue to pass

---

## Consumption summarization window: local-day bucketing and cross-job consistency (#443)

**Blocked by**: #440 (shared local-day helper)

**User stories**: 1, 4, 5

### What to build

`MariaDBClient.read_consumption_summarization_window` currently groups raw `consumption` by `func.date(period_from)` (UTC date) in SQL. Change it to fetch raw rows and group by Europe/London local calendar day in Python using the shared local-day helper, so the weekly `ConsumptionSummaryRetriever.refresh()` job stays consistent with `ConsumptionSummaryBackfill` (which already buckets by local day, since it reads `point.start.date()` directly off Octopus's still-locally-offset API response before any DB round-trip, and is unaffected by this change).

### Acceptance criteria

- [ ] Raw consumption is grouped into the summarization window by Europe/London local calendar day, not UTC date
- [ ] A case with consumption spanning a UTC-midnight boundary that is not a local-midnight boundary produces the same day attribution the one-time `ConsumptionSummaryBackfill` would produce for the same underlying readings
- [ ] All existing tests in `tests/test_consumption_summarization.py` continue to pass (daily totals per energy, stale-summary correction, gap-day summarization, 14-day trailing window boundary)

---

## Grafana reference queries: local-time day/hour grouping (#444)

**Blocked by**: None

**User stories**: 6

### What to build

In `grafana/mariadb/queries.md`, wrap every grouping/labeling expression that currently reads `period_from` directly in `CONVERT_TZ(period_from, 'UTC', 'Europe/London')`: every `DATE(...)` used for day-bucketing, `HOUR(...)` in the Hour×Day-of-Week heatmap, and `DAYNAME(...)` in the day-of-week panels. Add a short standing note near the file's "Schema assumed" section documenting this local-time convention, alongside the existing half-open-window join convention.

### Acceptance criteria

- [ ] Every panel that currently groups or labels by `period_from`'s raw date (Yesterday's Cost, p/kWh Efficiency, Daily Average Cost, Daily Average Usage, Day-of-Week Average, Standing Charge split, Gas Consumption, Gas Cost) uses `CONVERT_TZ(period_from, 'UTC', 'Europe/London')` for that grouping/labeling
- [ ] The Hour×Day-of-Week heatmap's `HOUR(...)` grouping uses local time
- [ ] Queries that don't group by day or hour (Price Curve, Half-hourly Consumption, Half-hourly Cost, Cheapest N-Hour Window, the Health row, the Yearly Comparison panels reading from `daily_consumption_summary`) are untouched
- [ ] A standing note documents the local-time convention for future panels added to this file
- [ ] After the app-side fix is deployed and the raw `consumption` table is wiped and repopulated, re-running the corrected Yesterday's Cost query against production matches Octopus's official value for a known day

---

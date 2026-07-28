# Day completeness guard for cost/consumption panels and the billing-period forecast

## Problem Statement

Octopus's consumption API has a real settlement lag: confirmed directly against the production account, a calendar day can still be sitting at 2/48 or even 0/48 half-hourly rows more than 24 hours after it ended, filling in gradually over the following day or two. Every panel and calculation that groups by calendar day treats whatever rows currently exist for that day as the day's final total — so "Yesterday's Cost" (and every other day-grouped Grafana panel, plus the billing-period cost forecast) can show a wildly, misleadingly low figure for a day that simply hasn't finished arriving from Octopus yet. This was discovered while investigating a separate, much smaller (~1-2%) estimated-vs-billed cost gap (issue #434) — this lag is a bigger and more common practical problem than that gap.

## Solution

Any query or calculation that groups by calendar day guards on that day being complete (48 half-hourly rows) before treating its total as final — mirroring the week-completeness idiom (`HAVING COUNT(*) = 7`) already used for the Yearly Comparison panels. The guard applies only to **strictly past** days; the current, still-in-progress day is exempt, since it's expected to be partial by definition ("cost so far").

- **Grafana panels**: Yesterday's Cost, Half-hourly Cost, p/kWh Efficiency, Standing Charge split, Daily Average Cost rolling, Gas Cost, and Gas Consumption all exclude incomplete days. Yesterday's Cost specifically falls back up to 7 days to the most recent complete day, and the panel shows which date it's actually displaying (not just assuming "yesterday").
- **Billing-period forecast** (`CostForecastRetriever`): `read_elapsed_billing_period_costs` applies the same guard to elapsed (non-today) days. An incomplete past day disappears from the query result and is picked up by the existing `_fill_zero_consumption_days` gap-fill — the same standing-charge-only treatment a genuine zero-consumption day already gets (see ADR-0009 for why this was chosen over fully excluding the day). That gap-filled day is then excluded from the daily-average-consumption input used to project remaining cost, so a data-arrival gap can't drag the projection down.

Out of scope for this piece of work: the separate billing-statement/ledger reconciliation feature (deferred to a future issue — see Further Notes).

## User Stories

1. As the dashboard user, I want "Yesterday's Cost" to never show a near-zero total just because Octopus hasn't finished publishing that day's readings yet, so that I can trust the number at a glance without knowing about Octopus's settlement lag.
2. As the dashboard user, I want to know which date "Yesterday's Cost" is actually showing when it has fallen back to an earlier day, so that I'm not misled into thinking a stale figure is today's.
3. As the dashboard user, I want the other day-grouped electricity/gas panels (Half-hourly Cost, p/kWh Efficiency, Standing Charge split, Daily Average Cost rolling, Gas Cost, Gas Consumption) to simply omit a still-arriving day rather than plot a misleading low bar/point for it.
4. As the dashboard user, I want "This Billing Period's Cost So Far" and "Total Expected Cost" to keep accruing correctly (standing charge still counted) even when a recent day's consumption hasn't fully arrived yet, and to self-correct automatically once it does, without needing a manual refresh or intervention.
5. As the dashboard user, I want the future-cost projection to be based on real, complete days of usage, so a data-arrival gap doesn't quietly make my projected bill look lower than it will actually be.

## Implementation Decisions

- **`app/data/mysql/client.py` — `read_elapsed_billing_period_costs`**: add a completeness filter to the per-day aggregation. For any day strictly before `period_to`'s date (the caller always passes `as_of` as `period_to`, so "today" is `period_to`'s date and stays exempt), require the day's row count to equal 48; days that don't meet this are dropped from the result entirely, same as a day with zero consumption rows already is.
- **`app/data/model.py` — `DailyCostSummary`**: add a boolean field marking a row as gap-filled (constructed by `_fill_zero_consumption_days`, not by a real join result). This is the explicit signal the projection-input filter uses — deliberately not inferring "filled" from `total_kwh == 0`, since a future maintainer could reasonably want to distinguish a genuine zero-usage day from a data gap later, and an implicit zero-value check would silently conflate the two.
- **`app/data/cost_forecast.py` — `CostForecastRetriever._project_remaining_cost`**: when building the input to `project_daily_average_consumption`, filter out gap-filled entries first. `project_daily_average_consumption` itself is unchanged — it still averages whatever list it's given (existing tests for it, including the zero-consumption-days-included-in-the-average case, stay valid and untouched); the filtering happens at the call site before that list is built.
- **`grafana/mariadb/queries.md`**: every query grouping by `DATE(period_from)` for the affected panels gains a completeness guard. The established SQL shape: join to a per-day row-count subquery/CTE (or a `HAVING COUNT(*) = 48` on the existing day-level `GROUP BY`, whichever composes more cleanly per query — most of these queries already `GROUP BY DATE(c.period_from)`, so `HAVING COUNT(*) = 48` is likely a direct, minimal addition). Yesterday's Cost additionally needs to search backwards (up to 7 days) for the most recent day meeting the guard, and return that day's date alongside its cost — this one panel's query shape changes more than a simple `HAVING` addition (it currently assumes exactly one target day).
- No changes to `ConsumptionRetriever`/its forward-only watermark — the lag is real Octopus-side behavior, not a bug in our fetch cadence (already confirmed: `consumption_refresh` runs hourly and succeeds; it simply has nothing new to fetch until Octopus publishes it, and the existing watermark-forward design already self-heals once new data appears upstream).

## Testing Decisions

Prefer the existing seams already used for this exact code:

- **`tests/test_elapsed_billing_period_costs.py`** (direct `MariaDBClient.read_elapsed_billing_period_costs` seam, real SQLite-backed `mariadb_client` fixture): add cases for — a past day with fewer than 48 rows is excluded from the result; a past day with exactly 48 rows is included; the current/most-recent day (`period_to`'s date) is included regardless of row count.
- **`tests/test_cost_forecast_retriever.py`** (highest seam — `CostForecastRetriever.refresh()` end to end against the real `mariadb_client`, same pattern as the existing zero-consumption-day gap-fill test): add a regression test where a past elapsed day has partial rows (e.g. 2 of 48) — assert `actual_cost_to_date` reflects standing-charge-only for that day (mirroring `test_a_zero_consumption_elapsed_day_still_contributes_its_standing_charge`), and assert the projected remaining cost's daily-average input excludes that day (i.e. the projection isn't dragged down by the partial day's near-zero consumption).
- **`tests/test_future_consumption_projection.py`**: no change expected — `project_daily_average_consumption`'s own contract is untouched; the filtering happens one level up at the call site.
- **Grafana queries (`grafana/mariadb/queries.md`)**: no automated test seam exists for these today (confirmed — no test file references `queries.md` or "grafana"). Prior art from the half-open-window join fix: validated manually via direct SQL against the database (the `docker --context pi4 exec energy-monitor-db ... mariadb ...` technique already documented in this repo's session history) and, where practical, against the live Grafana instance. Continue that approach here rather than introducing new test infrastructure for documentation-only SQL.

## Out of Scope

- The billing-statement/ledger reconciliation feature (real billed cost vs. recomputed estimate) — deferred to a separate future issue.
- `smartMeterTelemetry`-based real-time cost — investigated and ruled out this session: it returns zero rows for the production account across its entire queryable 30-day window, so there's no live data source to build on for this account.
- Any change to `ConsumptionRetriever`'s fetch/watermark logic — the lag is Octopus-side and the existing forward-only watermark already self-heals once data is published.
- Gas telemetry, or any other fuel/data-source expansion beyond the completeness guard itself.

## Further Notes

- The settlement-lag finding was confirmed directly against the live production account this session: `job_run` shows `consumption_refresh` succeeding hourly throughout 07-27, yet the stored `consumption` table has only 2/48 electricity rows and 0/48 gas rows for that day, and a fresh live query against Octopus's REST consumption API for the same window returned zero rows — proving the gap is Octopus-side data availability, not a stalled or broken job.
- New domain term **Day Completeness** added to `.agent-docs/context.md`; new **ADR-0009** records the standing-charge-floor-fallback decision and why full exclusion was rejected.
- A follow-up issue should capture the deferred billing-statement feature: Kraken GraphQL `account.ledgers.statements.transactions` (`BillCharge` nodes) returned real, well-structured data for the production account when spiked this session — `amounts.gross/net/tax` in integer pence (confirmed), `consumption.quantity` as a string needing `Decimal` parsing, and multiple `BillCharge` lines per fuel possible within one statement (mid-cycle tariff changes) alongside non-charge `BillPayment` transactions that must be filtered out.

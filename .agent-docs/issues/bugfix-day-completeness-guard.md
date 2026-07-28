# Issues: bugfix-day-completeness-guard

## Completeness guard for the billing-period cost forecast pipeline

**Issue**: #436

**Blocked by**: None

**User stories**: 4, 5

### What to build

`DailyCostSummary` gains a flag marking a row as gap-filled (constructed by `_fill_zero_consumption_days`, not derived from a real join result). `read_elapsed_billing_period_costs` applies a per-day completeness guard (48 half-hourly rows required) to every day strictly before the query's `period_to` date — the current/most-recent day stays exempt since it's expected to be partial by definition. A day that fails the guard simply disappears from the result, exactly like a day with zero consumption rows already does, and is picked up by the existing gap-fill path (standing-charge-only, same as a genuine zero-consumption day). `_project_remaining_cost` filters out gap-filled entries before building the input to `project_daily_average_consumption`, so a data-arrival gap can't drag the future-cost projection down. `project_daily_average_consumption` itself is untouched.

### Acceptance criteria

- [ ] A past day with fewer than 48 stored rows is excluded from `read_elapsed_billing_period_costs`'s result.
- [ ] A past day with exactly 48 stored rows is included as normal.
- [ ] The current/most-recent day (`period_to`'s date) is included regardless of row count.
- [ ] `CostForecastRetriever.refresh()`, run end to end against a real (SQLite-backed) `MariaDBClient`, shows a past day with partial rows contributing standing-charge-only to `actual_cost_to_date` (same treatment as the existing zero-consumption-day test).
- [ ] In that same scenario, the partial day is excluded from the daily-average input driving the remaining-cost projection — the projection is not dragged down by the partial day's near-zero recorded consumption.
- [ ] Existing tests in `test_future_consumption_projection.py` and `test_cost_forecast_retriever.py` continue to pass unchanged.

---

## Completeness guard for day-grouped Grafana panels

**Issue**: #437

**Blocked by**: None

**User stories**: 3

### What to build

Add a `HAVING COUNT(*) = 48` completeness guard (per calendar day) to every remaining day-grouped query in `grafana/mariadb/queries.md` that isn't Yesterday's Cost: Half-hourly Cost, p/kWh Efficiency, Standing Charge split, Daily Average Cost rolling, Gas Cost, and Gas Consumption. A day that doesn't meet the guard is simply omitted from that panel's results — no bar/point plotted for a still-arriving day — mirroring the existing week-completeness idiom already used for the Yearly Comparison panels.

### Acceptance criteria

- [ ] Each of the six queries excludes any calendar day with fewer than 48 `consumption` rows for the relevant energy type from its results.
- [ ] A fully-populated day (48 rows) is unaffected and still appears exactly as before.
- [ ] Changes validated manually against the live/dev database (direct SQL, same technique used for the prior half-open-window join fix) — before/after row counts confirmed for at least one currently-incomplete day and one complete day.

---

## Yesterday's Cost fallback to the most recent complete day

**Issue**: #438

**Blocked by**: None

**User stories**: 1, 2

### What to build

Redesign the Yesterday's Cost query so that, instead of assuming `CURDATE() - INTERVAL 1 DAY` is always complete, it searches backwards (up to 7 days) for the most recent day meeting the 48-row completeness guard, and returns that day's date alongside its cost. The Grafana panel is updated to display both the cost and the date it actually covers, so a fallback to an earlier day is never silently mislabeled as "yesterday."

### Acceptance criteria

- [ ] When yesterday is complete (48 rows), the panel shows yesterday's cost and yesterday's date, matching current behavior.
- [ ] When yesterday is incomplete, the query returns the most recent day within the last 7 days that is complete, along with its cost.
- [ ] If no day within the last 7 days is complete, the panel shows no data rather than a misleading partial figure.
- [ ] The panel's displayed date always matches the day the displayed cost actually covers.
- [ ] Changes validated manually against the live/dev database, using the currently-incomplete day (07-27) observed this session as a live test case.

---

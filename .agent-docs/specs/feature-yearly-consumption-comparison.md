# Yearly Consumption Comparison

## Problem Statement

There's no way to see consumption trends over a year or compare how a given week's usage stacks up against the same week the year before. Raw half-hourly `consumption` data exists, but nothing summarizes it at a useful granularity for that kind of long-range view — and with `retention_days` reverting to 45 days (see [ADR-0003](../adr/0003-90-day-data-retention.md) and `chore/consumption-data-pruning`), raw data won't even be around long enough to compute a 12-month or 52-week comparison directly.

## Solution

Build a pruning-exempt daily aggregate table, populated by a new weekly job, and add two new Grafana panels that read from it: a 12-month trailing view of monthly total consumption, and a week-over-week year-on-year comparison by ISO week number. Both are split by energy (electricity and gas tracked separately, consistent with how the rest of the dashboard treats the two fuels).

## User Stories

1. As the account holder, I want to see total consumption for each of the last 12 calendar months, labelled by month and year, so that I can spot seasonal trends at a glance.
2. As the account holder, I want to see, for each of the last 52/53 weeks, how much more or less energy I used compared to the same week number a year earlier, so that I can tell whether my usage is trending up or down year-on-year rather than just month-to-month.
3. As the account holder, I want that week-on-week comparison smoothed as well as shown raw, so that a single unusual week (e.g. a cold snap or being away) doesn't dominate the reading.
4. As the account holder, I want electricity and gas shown as separate series/panels, so that gas's much larger winter swings don't obscure electricity's flatter profile.
5. As the operator, I want these panels to still be correct after the pruning job starts deleting raw data older than 45 days, so that a storage-hygiene change elsewhere doesn't quietly break a dashboard feature.

## Implementation Decisions

- New table `daily_consumption_summary(energy, date, total_kwh)`, composite primary key `(energy, date)`. Added to `app/data/mysql/model.py` (picked up automatically by the existing additive schema sync, [ADR-0005](../adr/0005-additive-only-schema-sync.md) — no `init.sql` change needed). Deliberately exempt from the pruning job, the same treatment established for `cost_forecast` (`feature/agile-cost-forecast`) — this is derived/aggregated data, not raw interval data.
- New module `app/data/consumption_summary.py`:
  - `ConsumptionSummaryRetriever` (or similar), mirroring the shape of `ConsumptionRetriever`/`PricingRetriever`. Its `refresh()`:
    1. Determines the summarization window: the trailing 14 days, plus any date with raw `consumption` rows but no existing `daily_consumption_summary` row (covers the case where the app was down long enough that a gap opened up).
    2. For each `(energy, date)` in that window, sums `est_kwh` from `consumption` grouped by `DATE(period_from)` and `energy`, and upserts the result into `daily_consumption_summary` via the existing `upsert`/`session_write_scope` pattern (`MariaDBClient.write_consumption_summary`, following `write_agreement`/`write_product_rate`'s shape).
    3. Re-summarizing the trailing 14 days every run (rather than only ever-unsummarized days) absorbs upstream Octopus consumption corrections — smart-meter readings are sometimes estimated and revised after the fact, and `ConsumptionRetriever` already treats re-fetch-and-upsert as the norm rather than a one-time snapshot.
- New scheduled job `update_consumption_summary`, registered on a weekly cadence (distinct from the existing hourly-ish `refresh_interval_hours` cadence used by consumption/pricing refresh — this needs its own scheduler entry and its own interval, e.g. a new `weekly_maintenance` job group), wrapped in the existing `job_run` mechanism. As of `bugfix/consumption-timezone-and-scheduler-backoff`, `_schedule_refresh_job` dispatches to a per-job background thread with exponential-backoff retries (not a plain try/except) — reuse that same mechanism/helper for consistency rather than the simpler pattern this spec originally assumed, so a persistently-failing weekly job also backs off instead of retrying every tick.
- Two new panels documented in `grafana/mariadb/queries.md` (SQL-only addition to that document — no dashboard exists to wire them into yet; see `feature-grafana-dashboard.md`, still unimplemented):
  - **Monthly Total Consumption — Last 12 Months** (bar/time series, one per energy): `SELECT DATE_FORMAT(date, '%b %Y') AS month, SUM(total_kwh) AS monthly_kwh FROM daily_consumption_summary WHERE energy = 'E' AND date >= DATE_FORMAT(CURDATE() - INTERVAL 11 MONTH, '%Y-%m-01') GROUP BY DATE_FORMAT(date, '%Y-%m') ORDER BY MIN(date);` (and the `energy = 'G'` equivalent). The cutoff is anchored to the first day of the month 11 months ago (not `CURDATE() - INTERVAL 12 MONTH`, which yields a partial *oldest* month rather than 12 full calendar-month buckets) — giving exactly 12 monthly buckets: 11 complete months plus the current, naturally-partial-in-progress month. `DATE_FORMAT(date, '%b %Y')` produces the agreed "Jan 2026"-style label.
  - **Weekly Year-on-Year Change — Last 52/53 Weeks** (time series, two series: raw % and 4-week moving average, one panel per energy): group `daily_consumption_summary` by `YEARWEEK(date, 3)` — **not** `YEAR(date)` paired separately with `WEEK(date, 3)`, since `WEEK(date, 3)` alone only returns the week number; combining it with the row's calendar `YEAR(date)` can misattribute early-January/late-December boundary dates to the wrong week-year, exactly the edge case ISO week numbering exists to avoid. `YEARWEEK(date, 3)` (mode 3 = ISO week numbering) returns the correctly-paired ISO year+week directly, avoiding the "week 0" ambiguity of MySQL's default mode 0, where early-January days before the first Sunday get bucketed into a non-standard partial week. Self-join each week to the same ISO week number one year prior via `YEARWEEK(date, 3) = YEARWEEK(target_date, 3) - 100` (subtracting 100 shifts back exactly one week-year while preserving the same week number, e.g. `202630 - 100 = 202530`), compute `(this_year_total - last_year_total) / last_year_total * 100` as the raw series, then a `AVG(...) OVER (ORDER BY yearweek ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)` as the 4-week trailing moving average series. When the current year has an ISO week 53 but the prior year tops out at week 52, that week's comparator falls back to the prior year's week 52 rather than being left null.
- `chore/consumption-data-pruning` depends on this branch: its weekly `prune_old_data` job only runs if that cycle's `update_consumption_summary` job succeeded, so raw data is never deleted before it's been rolled into `daily_consumption_summary`.

## Testing Decisions

- `ConsumptionSummaryRetriever`/`update_consumption_summary`: tested against a seeded SQLite in-memory session (the same seam already used by `test_pricing_retrieval.py`/`test_agreement_persistence.py`) — seed `consumption` rows across several days for both energies, run the summary job, assert the resulting `daily_consumption_summary` rows match expected daily totals per energy.
- Re-summarization/correction case: seed a day's summary row with a stale total, then seed `consumption` rows for that same day with a different total (simulating an upstream correction within the trailing-14-day window), run the job, assert the summary row is updated to the corrected total.
- Gap-catching case: seed raw `consumption` for a day older than 14 days with no existing summary row, run the job, assert that day gets summarized too.
- `MariaDBClient.write_consumption_summary`: unit test asserting upsert-on-conflict behaviour, mirroring existing coverage for `write_agreement`/`write_product_rate`.
- Job scheduling/failure handling: extend `test_refresh_scheduling.py`'s existing pattern (`Mock(spec=...)` retriever, assert `job_run` records success/failure) to cover the new weekly job registration.
- No automated test for the Grafana panel SQL itself — same testing decision already made in `feature-grafana-dashboard.md` for panel queries: `grafana/mariadb/queries.md` is the source of truth for query SQL, verified against a real MariaDB instance when the dashboard feature itself is implemented, not here.

## Out of Scope

- The Grafana dashboard/provisioning itself (`feature/grafana-dashboard` — still unimplemented; this spec only adds query definitions to `grafana/mariadb/queries.md`).
- The pruning job and the `retention_days` revert to 45 (`chore/consumption-data-pruning` — a separate, dependent spec).
- The one-time database wipe and 2-year deep-backfill migration needed to seed `daily_consumption_summary` with enough history for the full 52/53-week comparison — covered in `chore/consumption-data-pruning`'s spec, since it's driven by that branch's retention-window change, not this one.
- Any change to the existing hourly consumption/pricing refresh cadence.

## Further Notes

Full rationale (why `daily_consumption_summary` exists at all, why ISO week numbering, the moving-average definition, and the retention-window interaction) is recorded in this session's `/grill` transcript and in the revised [ADR-0003](../adr/0003-90-day-data-retention.md). New glossary terms **Consumption Summary** and **Yearly Comparison** are documented in `.agent-docs/context.md`.

---
status: accepted
---

# Prune raw consumption/cost/rate data after 45 days

Half-hourly consumption, cost, and product-rate data accumulates indefinitely if never pruned. We decided a pruning job should delete raw rows older than 45 days, rather than keeping full history forever, because the app runs on Pi-class hardware where unbounded MariaDB growth is an operational risk. Computed/aggregated results (e.g. `cost_forecast`, `daily_consumption_summary`) are unaffected — pruning applies to raw interval data only, not derived summaries. (The tariff-comparison feature and its `tariff_comparison_result`/Agile-vs-Variable-savings tables, originally cited here as an example of exempt derived data, were dropped entirely during `feature/agile-cost-forecast`'s reconciliation — see that spec's Further Notes.)

`retention_days` was briefly widened from 90 to 400 days as a stopgap, to keep raw data around long enough for a not-yet-built historical summarization pass to draw on. `feature/yearly-consumption-comparison` replaced that stopgap with a dedicated one-time 2-year backfill (`ConsumptionSummaryBackfill`) that fetches directly from Octopus's API into `daily_consumption_summary`, independent of `retention_days` — so `retention_days` reverted to 45 as part of that branch, without waiting for the pruning job itself.

**The pruning job is not yet implemented.** As of this revision, nothing in
the codebase actually deletes old rows — data grows unbounded today. The
45-day number is, for now, only the value `config.yml`'s `retention_days`
uses to bound the startup historical backfill (see
`app/main.py`'s `startup()` and `RefreshSettings.retention`); the pruning
job described above (`chore/consumption-data-pruning`) is separate, future
work.

## Consequences

- Once the pruning job is built, no month-over-month comparison of raw data
  beyond 45 days back — `daily_consumption_summary` (populated independently
  of raw-data retention) is the source of truth for anything longer-range.
- Until the pruning job exists, `retention_days` only governs how far back
  the startup backfill reaches — it does not yet bound storage growth.

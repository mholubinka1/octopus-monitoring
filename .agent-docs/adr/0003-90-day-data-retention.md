---
status: accepted
---

# Prune raw consumption/cost/rate data after 45 days

Half-hourly consumption, cost, and product-rate data accumulates indefinitely if never pruned. We decided a pruning job should delete raw rows older than 45 days, rather than keeping full history forever, because the app runs on Pi-class hardware where unbounded MariaDB growth is an operational risk. Computed/aggregated results (e.g. `cost_forecast`, `daily_consumption_summary`) are unaffected — pruning applies to raw interval data only, not derived summaries. (The tariff-comparison feature and its `tariff_comparison_result`/Agile-vs-Variable-savings tables, originally cited here as an example of exempt derived data, were dropped entirely during `feature/agile-cost-forecast`'s reconciliation — see that spec's Further Notes.)

`retention_days` was briefly widened from 90 to 400 days as a stopgap, to keep raw data around long enough for a not-yet-built historical summarization pass to draw on. `feature/yearly-consumption-comparison` replaced that stopgap with a dedicated one-time 2-year backfill (`ConsumptionSummaryBackfill`) that fetches directly from Octopus's API into `daily_consumption_summary`, independent of `retention_days` — so `retention_days` reverted to 45 as part of that branch, without waiting for the pruning job itself.

**The pruning job is now implemented** (`chore/consumption-data-pruning`).
`DataPruner` (`app/data/pruning.py`) runs as the `prune_old_data` step,
executed as a continuation of the `update_consumption_summary` job within
the same Monday 04:00 scheduled job and the same background worker thread
— not as a second, independently-scheduled job. That's deliberate: the
summary job dispatches via a retry-with-backoff background thread that
returns before the work completes, so a separately-scheduled prune job
sharing the same time slot could race it, checking whichever `job_run` was
most recently recorded (e.g. last week's) rather than this cycle's real
outcome. Sequencing it as a continuation makes that race impossible.
It deletes `consumption` rows where `period_from` is older than
`retention_days`, and `product_rate` rows where `valid_to` is older than
that same cutoff — a still-valid or open-ended (`valid_to IS NULL`) rate is
never pruned. `agreement` is never touched. After summarization completes,
it checks that this cycle's `update_consumption_summary` run recorded a
successful `job_run`; if not, pruning is skipped for that cycle (recorded
as its own `job_run` with status `skipped`) so raw data is never deleted
before it has been rolled into `daily_consumption_summary`.

## Consequences

- No month-over-month comparison of raw data beyond 45 days back —
  `daily_consumption_summary` (populated independently of raw-data
  retention) is the source of truth for anything longer-range.
- `retention_days` now bounds both the startup backfill's lookback and
  ongoing storage growth, since the weekly pruning job enforces it.

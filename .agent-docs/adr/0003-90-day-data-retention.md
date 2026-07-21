---
status: accepted
---

# Prune raw consumption/cost/rate data after 400 days

Half-hourly consumption, cost, and product-rate data accumulates indefinitely if never pruned. We decided a daily pruning job should delete raw rows older than 400 days, rather than keeping full history forever, because the app runs on Pi-class hardware where unbounded MariaDB growth is an operational risk. The window was widened from an originally-planned 90 days to 400 days to support dashboard elements needing a full year-plus of history. Computed/aggregated results (e.g. `cost_forecast`) are unaffected — pruning applies to raw interval data only, not derived summaries. (The tariff-comparison feature and its `tariff_comparison_result`/Agile-vs-Variable-savings tables, originally cited here as an example of exempt derived data, were dropped entirely during `feature/agile-cost-forecast`'s reconciliation — see that spec's Further Notes.)

**This pruning job is not yet implemented.** As of this revision, nothing in
the codebase actually deletes old rows — data grows unbounded today. The
400-day number is, for now, only the value `config.yml`'s `retention_days`
uses to bound the startup historical backfill (see
`app/main.py`'s `startup()` and `RefreshSettings.retention`); the daily
pruning job described above is separate, future work.

## Consequences

- Once the pruning job is built, no month-over-month comparison beyond
  roughly 400 days back, and no ability to retroactively analyze usage/price
  patterns older than that.
- If deeper historical analysis becomes a real need later, this must be
  revisited before it's needed — pruned rows will not be recoverable once
  pruning ships.
- Until the pruning job exists, `retention_days` only governs how far back
  the startup backfill reaches — it does not yet bound storage growth.

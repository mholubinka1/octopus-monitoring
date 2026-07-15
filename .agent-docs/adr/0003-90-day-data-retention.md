---
status: accepted
---

# Prune raw consumption/cost/rate data after 90 days

Half-hourly consumption, cost, and product-rate data accumulates indefinitely if never pruned. We decided to add a daily pruning job that deletes raw rows older than 90 days, rather than keeping full history forever, because the app runs on Pi-class hardware where unbounded MariaDB growth is an operational risk, and the longest trend panel on the dashboard (12-week rolling averages, day-of-week breakdown) only needs 84 days — 90 days leaves headroom without materially serving any other planned feature. Computed/aggregated results (`tariff_comparison_result`, cumulative Agile-vs-Variable savings) are unaffected — pruning applies to raw interval data only, not derived summaries.

## Consequences

- No month-over-month comparison beyond roughly two months back, and no ability to retroactively analyze usage/price patterns older than 90 days once this ships.
- If deeper historical analysis becomes a real need later, this must be revisited before it's needed — pruned rows are not recoverable.

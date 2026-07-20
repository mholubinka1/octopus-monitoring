# Agile Cost Forecast

## Problem Statement

Knowing what you've spent so far this billing period doesn't tell you what the bill will actually be at month-end — with Agile's daily-changing prices, month-end cost is genuinely uncertain until the period is over.

## Solution

Consume `agile_predict`'s public 14-day-ahead price forecast API (see [ADR-0002](../adr/0002-agile-predict-forecast-dependency.md)) to project month-end electricity cost from month-to-date actual cost plus forecast prices for the remainder of the billing period, and track cumulative Agile-vs-Variable savings over time so the 400-day retention/pruning policy ([ADR-0003](../adr/0003-90-day-data-retention.md)) doesn't erase that history.

## User Stories

1. As the account holder, I want to see a projected month-end electricity cost, so that I have some warning before the bill arrives rather than being surprised.
2. As the account holder, I want to see how much I've saved by being on Agile vs. the standard variable tariff, cumulatively rather than just for the current billing period, so that I can judge whether Agile has been worth it over time.
3. As the operator, I want to know if the forecast data source (`prices.fly.dev`) is unreachable, so that a stale or missing forecast is visible rather than silently wrong.

## Implementation Decisions

- New table `agile_forecast(id, region, period_from, period_to, forecast_unit_rate, fetched_at)`.
- New table `daily_saving(date PK, actual_cost, variable_cost, saving)` — deliberately exempt from the 400-day pruning job (ADR-0003) as a derived daily summary, not raw interval data.
- New module `app/data/forecast.py`:
  - `AgilePredictClient` — HTTP client for `GET https://prices.fly.dev/v2/<region>/`, parsed into `agile_forecast` rows.
  - `project_month_end_cost(actual_cost_to_date, forecast_rates, avg_daily_usage, billing_period_end) -> Decimal` — pure function combining month-to-date actual cost with forecast-rate-priced remaining days, using a trailing average daily usage as the consumption assumption for future days (a documented simplification — no per-half-hour usage forecast).
- A daily job (same cadence as tariff comparison):
  1. Fetches the forecast, upserts `agile_forecast`.
  2. Computes `projected_month_end_cost` and writes it onto the current period's `tariff_comparison_result` row (from `feature/cheapest-tariff-comparison`).
  3. Computes and appends today's `daily_saving` row — actual cost vs. simulated Variable-tariff cost for today, reusing the `simulate_cost` pure function from `feature/cheapest-tariff-comparison` against the `${variable_product_code}` baseline (see `.agent-docs/grafana-queries.md` for the caveat that this baseline needs manual upkeep as Octopus rotates product codes).
- Every run of the forecast-fetch job records its outcome via `record_job_run(job_name="fetch_agile_forecast", ...)` — this is what the dashboard's health panel reads to show `prices.fly.dev` reachability.
- On fetch failure: log and record the failed `job_run`, leave existing `agile_forecast` data in place (graceful degradation, matching `agile_predict`'s own documented behaviour) rather than blocking the rest of the daily job.

## Testing Decisions

- `AgilePredictClient` tested via `responses`-mocked `prices.fly.dev` responses, including a failure/unreachable case asserting graceful degradation and that `job_run` records the failure.
- `project_month_end_cost` is a pure-function unit test with fixture actual-cost/forecast-rate/usage data, covering: forecast not covering the full remainder of the billing period, zero-usage days.
- The daily job end-to-end is tested against a seeded SQLite in-memory session, asserting `tariff_comparison_result.projected_month_end_cost` and a new `daily_saving` row are written correctly.

## Out of Scope

Building an in-house forecasting model (explicitly rejected — see ADR-0002). Dashboard panel work (`feature/grafana-dashboard`). Automated actions based on forecast (e.g. load-shifting automation) — declined during the design session.

## Further Notes

Depends on `feature/tariff-pricing-pipeline` (`agreement`/`product_rate`) and `feature/cheapest-tariff-comparison` (the `tariff_comparison_result` row to update, and `simulate_cost` reused for the savings calc). See **Agile Predict**, **Cost Forecast**, and **Retention Window** in `.agent-docs/context.md`.

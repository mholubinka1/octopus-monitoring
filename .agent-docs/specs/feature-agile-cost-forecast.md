# Cost and Cost Forecast

## Problem Statement

The app tracks consumption and rates but surfaces no actual spend at all — not yesterday's cost, not this billing period's cost so far, and no forward-looking sense of what the current bill will come to before it's issued. With Agile's daily-changing prices, month-end cost is genuinely uncertain until the billing period is over.

This supersedes the earlier `feature/cheapest-tariff-comparison` spec, which is dropped entirely (no tariff-comparison/ranking feature is wanted) — see Further Notes for what carries forward from it.

## Solution

Two related but differently-scoped pieces:

1. **Actual Cost** — "yesterday's cost" and "this billing period's cost so far," computed from real consumption × the real rates actually charged (already fully available via `consumption` ⋈ `agreement` ⋈ `product_rate` — no new Octopus API integration needed for the data itself).
2. **Cost Forecast** — "total expected cost for this billing period," combining actual cost to date with a forecast for the remaining days, using AgilePredict's public price forecast and a usage projection based on this period's own consumption so far.

Both need to know the account's real billing period boundaries, which requires a new integration: Octopus's GraphQL "Kraken" API (the REST v1 API this app already uses has no billing-period data at all — see `.agent-docs/research/octopus-billing-period-api.md`).

## User Stories

1. As the account holder, I want to see yesterday's electricity cost, so that I have an immediate, simple cost figure without waiting for a billing cycle.
2. As the account holder, I want to see this billing period's cost so far, so that I know where I stand partway through a cycle.
3. As the account holder, I want to see the total cost I should expect for this billing period, so that I have some warning before the bill arrives rather than being surprised.
4. As the operator, I want the billing period's real start/end dates fetched from Octopus rather than assumed, so that the numbers line up with what actually appears on a real bill.
5. As the operator, I want a defined fallback for accounts on flexible billing (no fixed end date from Octopus), so that the forecast still has a well-defined period to project to.
6. As the operator, I want to know if the forecast data source (AgilePredict) or the billing-period lookup (Kraken) is unreachable, so that a stale or missing forecast is visible rather than silently wrong.

## Implementation Decisions

### Billing period (new: GraphQL Kraken client)

- New small GraphQL client (sibling to `OctopusTransport`, not a replacement — a second lightweight HTTP client POSTing JSON to `https://api.octopus.energy/v1/graphql/`), reusing the existing stored API key.
- Mint a short-lived JWT per run via `obtainKrakenToken(input: {APIKey: "<existing_key>"})` — confirmed live against this account (see the research doc's Smoke Test section): the account-user API key is accepted at the resolver level, no customer email/password needed or stored. Re-authenticate every run rather than persisting/rotating a refresh token.
- Query `account(accountNumber: "...") { billingOptions { currentBillingPeriodStartDate currentBillingPeriodEndDate isFixed } }`.
- **Flexible-billing fallback** (confirmed live: this account has `isFixed: false`, `currentBillingPeriodEndDate: null`): when `isFixed` is false, `billing_period_end = billing_period_start + 1 calendar month`, same day-of-month, clamped to the last valid day of that month if it doesn't exist (e.g. the 31st rolling back to the 28th/29th/30th). Recomputed fresh from whatever `currentBillingPeriodStartDate` currently is on every run — never cached/assumed to persist across runs.
- When `isFixed` is true, use `currentBillingPeriodEndDate` directly.

### Actual Cost

- **Yesterday's cost**: no new backend code — a live Grafana query joining `consumption` ⋈ `agreement` ⋈ `product_rate` for `period_from` between yesterday 00:00 and today 00:00. Doesn't depend on billing period at all.
- **This billing period's cost so far**: *does* need billing period boundaries, which only the app can fetch (Grafana has no way to call the Kraken API itself) — so this is computed by the app and persisted (see Cost Forecast table below), not a pure live query.

### Cost Forecast

- **Future consumption estimate**: average daily consumption over the billing period elapsed so far, projected flat across the remaining days.
- **Future price estimate** (Agile only — a fixed/variable tariff's future rate is just its current known `unit_rate`, no forecasting needed):
  - `AgilePredictClient` — HTTP client for `GET https://agilepredict.com/api/{region}/` (confirmed live, region matches the account's GSP code, no auth required). **Corrects the stale endpoint** in ADR-0002/the old spec (`prices.fly.dev/v2/<region>/`) — same underlying Fly.io-hosted service (identical server signature), but that path now serves the HTML frontend, not JSON; the real API has moved to `agilepredict.com/api/{region}/`.
  - Confirmed via live smoke test: the forecast horizon is a **hard 14-day cap** — `days`/`forecast_count` query params don't extend it (tested `days=31` and `days=100`; both return identical 14-day-out data). Published accuracy (`GET /api/accuracy/`) degrades sharply after day 1 (MAE 0.45 p/kWh at 0–24h) but then plateaus (MAE ~4.3–4.9 p/kWh from day 3 onward) — the 14-day forecast itself isn't meaningfully worse at the far end than the middle.
  - For the stretch of the billing period **beyond day 14**: tile the last 7 days of the 14-day forecast (days 8–14, the furthest-out predictions) repeating in sequence — day 15 reuses day 8's half-hourly pattern, day 16 reuses day 9's, and so on — until `billing_period_end` is reached. Preserves day-of-week/time-of-day shape rather than collapsing to a flat average.
- New table `agile_forecast(id, region, period_from, period_to, forecast_unit_rate, fetched_at)` — caches the raw half-hourly AgilePredict response (real 14-day data only, not the beyond-day-14 tiled extension) so the dashboard's Price Curve panel (today/tomorrow actual + forecast) has per-half-hour data to plot. The tiling logic is applied only internally when computing `cost_forecast`'s longer-horizon projection, not persisted point-by-point — a today/tomorrow chart never needs data past the real 14-day forecast window.
- New table `cost_forecast(id, billing_period_start, billing_period_end, actual_cost_to_date, projected_total_cost, computed_at)` — the app computes and persists both the actual-cost-to-date snapshot and the full-period projection together each run, so Grafana reads one row rather than needing to independently reconstruct billing-period boundaries.
- New daily job `cost_forecast_refresh` (not hourly — billing period/forecast doesn't need consumption-refresh cadence), using the same `job_run`-wrapped background-worker-thread mechanism established in `bugfix/consumption-timezone-and-scheduler-backoff`.
- On AgilePredict or Kraken unreachability: log and record the failed `job_run`, leave the previous `cost_forecast` row in place (graceful degradation) rather than blocking.

## Testing Decisions

- Kraken client: `responses`-mocked GraphQL POST responses, covering `isFixed: true` (real end date), `isFixed: false` (fallback calculation, including the month-length-clamping edge case), and an unreachable/error case.
- `AgilePredictClient`: `responses`-mocked forecast responses, including a 14-day-cap response and a failure/unreachable case asserting graceful degradation.
- The day-15-onward tiling logic: pure-function unit test with fixture 14-day forecast data, asserting the tiled sequence for a period extending well past day 14 matches days 8–14 repeated in order.
- The future-consumption projection (average of period-so-far): pure-function unit test with fixture consumption data.
- `cost_forecast_refresh` end-to-end: seeded test-DB session (fixture `consumption`/`agreement`/`product_rate` rows), asserting the written `cost_forecast` row's `actual_cost_to_date` and `projected_total_cost` match expected values for known fixture data.
- Edge cases: a billing period with a mid-period Agile rate change; zero-consumption days; a billing period end date landing beyond the forecast tiling's own reach (shouldn't happen given tiling continues indefinitely, but worth asserting termination).

## Out of Scope

- Any tariff comparison/ranking against other Octopus products — this was the entirety of the now-dropped `feature/cheapest-tariff-comparison` spec.
- VAT calculation — confirmed unnecessary: `product_rate` already stores Octopus's own VAT-inclusive `value_inc_vat` figures uniformly for every product, so there's no point in the cost calculation where a separate VAT step would apply.
- Cumulative Agile-vs-Variable savings tracking (`daily_saving` table, `${variable_product_code}` baseline) — this was tied to the dropped comparison feature's baseline concept; not requested for this feature.
- Gas cost forecasting — gas pricing is flat-rate, doesn't need forecasting; gas actual-cost panels remain simple consumption/cost queries (already possible today, no new work).
- Building an in-house forecasting model (declined — see ADR-0002; still valid, just pointed at the corrected endpoint).
- Dashboard panel work (`feature/grafana-dashboard`, also being reconciled).

## Further Notes

Depends on `feature/tariff-pricing-pipeline` (`agreement`/`product_rate`, already implemented). Does **not** depend on `feature/cheapest-tariff-comparison` (deleted) — `cost_forecast` is its own table, not a column added onto a comparison-result row. See **Agile Predict**, **Billing Period**, and **Cost Forecast** in `.agent-docs/context.md` (Cheapest Tariff's glossary entry should be removed as part of this reconciliation), and `.agent-docs/research/octopus-billing-period-api.md` for the full Kraken API research and live smoke-test results.

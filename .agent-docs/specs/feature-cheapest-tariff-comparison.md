# Cheapest Tariff Comparison

## Problem Statement

Being on Agile is a bet — without comparing actual spend against what other published Octopus tariffs would have cost for the same usage, there's no way to know if Agile is still the right choice.

## Solution

Once a day, simulate the account's actual electricity usage over the current billing period against every published Octopus domestic electricity product available in the account's region (using rate data from `feature/tariff-pricing-pipeline`), and surface the cheapest option and the potential saving.

## User Stories

1. As the account holder, I want to know, for the current billing period, what I'd have paid on every other available Octopus electricity product for the same usage, so that I can tell whether Agile is still worth it.
2. As the account holder, I want the comparison to use my actual billing period dates where possible, so that the numbers match what I'd see on a real Octopus bill.
3. As the operator, I want a sensible fallback billing period (a configured day-of-month) when the real billing dates aren't available from Octopus, so that the feature still works if that API integration fails or doesn't exist.
4. As the account holder, I want to see which product is cheapest and by how much, updated daily, so that the dashboard can show a live "you could be saving £X" figure.

## Implementation Decisions

- New table `tariff_comparison_result(id, billing_period_start, billing_period_end, actual_product_code, actual_cost, cheapest_product_code, cheapest_cost, projected_month_end_cost, computed_at)`. `projected_month_end_cost` is always written NULL by this spec — `feature/agile-cost-forecast` fills it in on the same row later, to avoid a cross-branch dependency.
- New module `app/data/tariff_comparison.py`:
  - `resolve_billing_period(octopus_client, config) -> (start, end)` — attempts the real Octopus billing-date API first, falls back to a new `config.billing.day_of_month` field (default consistent with existing config template conventions) if that call fails or the endpoint doesn't return usable dates.
  - `simulate_cost(usage: List[Consumption], rates: List[ProductRate]) -> Decimal` — pure function computing total cost (unit-rate cost + standing charge) for one product over given usage.
  - `TariffComparator` — orchestrates: load billing-period usage, load candidate products/rates from `product_rate` (filtered to `product.direction = 'IMPORT'`, region-matched, domestic electricity only), run `simulate_cost` per candidate plus the account's real `agreement`-derived actual cost, and persist the cheapest + actual result to `tariff_comparison_result`.
- Runs as a new daily scheduled job (via the `job_run`-wrapped mechanism from `chore/operational-hygiene`), on its own cadence separate from consumption/pricing refresh.

## Testing Decisions

- `simulate_cost` and `resolve_billing_period`'s fallback path are pure-function unit tests with fixture data — no DB, no HTTP.
- `resolve_billing_period`'s real-API path is tested via `responses`-mocked Octopus billing endpoint, including the failure-triggers-fallback case.
- `TariffComparator.run()` end-to-end is tested against a seeded SQLite in-memory session (fixture `consumption`, `agreement`, `product_rate` rows in; assert the written `tariff_comparison_result` row matches expected cheapest/actual costs).
- Edge cases: no candidate products available in region (write a result with `cheapest_product_code` NULL rather than crashing); a billing period that spans a mid-period Agile rate change.

## Out of Scope

Cost forecasting (`feature/agile-cost-forecast` fills in `projected_month_end_cost`). Dashboard panels displaying this data (`feature/grafana-dashboard`). Gas tariff comparison (explicitly declined during the design session — gas pricing is flat enough that comparison adds little value).

## Further Notes

Depends on `feature/tariff-pricing-pipeline` (needs `agreement` and `product_rate` populated). See **Billing Period** and **Cheapest Tariff** in `.agent-docs/context.md`.

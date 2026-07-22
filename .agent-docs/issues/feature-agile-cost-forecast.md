# Issues: feature-agile-cost-forecast

> Note: User Story 1 ("yesterday's electricity cost") is already fully
> satisfied — the "Yesterday's Cost" Grafana panel in
> `grafana/mariadb/queries.md` is a live query against existing
> `consumption`/`agreement`/`product_rate` tables with no dependency on
> billing-period data. No issue needed for it. Likewise, all three
> `cost_forecast`-reading panels ("This Billing Period's Cost So Far",
> "Total Expected Cost This Billing Period", "Current Billing Period") and
> the "Price Curve" panel (reads `agile_forecast`) already exist in
> `queries.md` from an earlier reconciliation pass — they are documentation
> input, not output, of this work. This feature is backend-only: the three
> issues below build the tables/clients/job those pre-written panels are
> waiting on.

## Kraken GraphQL client — billing period lookup (#420)

**Blocked by**: None

**User stories**: 4, 5, 6 (partial — client-side unreachability signal only)

### What to build

A new small GraphQL client, sibling to `OctopusTransport`
(`app/data/octopus/transport.py`) rather than an extension of it — different
host (`https://api.octopus.energy/v1/graphql/`), different wire format
(JSON-over-POST, not query-string GET), no response `Pydantic` model reuse
from the REST clients. Mint a short-lived JWT per call via
`obtainKrakenToken(input: {APIKey: "<existing_key>"})`, reusing
`OctopusAPISettings.api_key` — no new stored secret, no persisted/rotated
refresh token (re-authenticate every call). Query
`account(accountNumber: "...") { billingOptions { currentBillingPeriodStartDate
currentBillingPeriodEndDate isFixed } }`.

Billing period end date logic:

- `isFixed: true` → use `currentBillingPeriodEndDate` directly.
- `isFixed: false` (flexible billing, confirmed live on this account) →
  `billing_period_end = billing_period_start + 1 calendar month`, same
  day-of-month, clamped to the last valid day of that month if it doesn't
  exist (e.g. the 31st rolling back to the 28th/29th/30th). Recomputed fresh
  from whatever `currentBillingPeriodStartDate` currently is on every call —
  never cached across runs.

On an unreachable/error Kraken response, raise a clear exception rather than
swallowing it — the daily job (a later issue) is responsible for catching
this and recording a failed `job_run`; this client's job is only to fail
loudly.

### Acceptance criteria

- [ ] New client authenticates via `obtainKrakenToken(APIKey: ...)` and
      queries `billingOptions` for a given account number
- [ ] `isFixed: true` returns `currentBillingPeriodEndDate` directly as the
      billing period end
- [ ] `isFixed: false` computes `billing_period_end` as start + 1 calendar
      month, same day-of-month, clamped to the month's last valid day
      (tested with a start date on the 29th/30th/31st rolling into a
      shorter month)
- [ ] An unreachable/error Kraken response raises a clear exception (not
      silently swallowed or returning a sentinel)
- [ ] No JWT or refresh token is persisted across calls — every call
      re-authenticates via the stored API key
- [ ] Unit tests (`responses`-mocked GraphQL POST): `isFixed: true` case,
      `isFixed: false` fallback case (including the month-clamping edge
      case), and an unreachable/error case
- [ ] Existing test suite remains green

---

## AgilePredict client + forecast tiling + consumption projection (#421)

**Blocked by**: None

**User stories**: 3 (partial — forecast data source only), 6 (partial —
client-side unreachability signal only)

### What to build

A new `AgilePredictClient` HTTP client, `GET
https://agilepredict.com/api/{region}/`, no auth required (public service —
see ADR-0002 and its endpoint correction note). Returns the real 14-day
half-hourly forecast only; the API's forecast horizon is a hard 14-day cap
(confirmed live — `days`/`forecast_count` params don't extend it). On an
unreachable/error response, raise a clear exception (same reasoning as the
Kraken client above — job-level graceful degradation is a later issue's
responsibility).

New table `agile_forecast` (`id`, `region`, `period_from`, `period_to`,
`forecast_unit_rate`, `fetched_at`), added via the additive-only automatic
schema sync (ADR-0005) — persists only the raw 14-day forecast response, not
any tiled/extended projection. This is what backs the pre-existing "Price
Curve" Grafana panel.

Two pure functions, independently unit-testable without any live API or DB:

- **Tiling**: given a 14-day forecast and a target end date beyond day 14,
  produce a tiled sequence — day 15 reuses day 8's half-hourly pattern, day
  16 reuses day 9's, and so on (days 8–14, the furthest-out predictions,
  repeating in sequence) until the target date is reached. Preserves
  day-of-week/time-of-day shape rather than collapsing to a flat average.
  This tiled data is computed on demand, not persisted point-by-point.
- **Consumption projection**: given consumption data for the elapsed portion
  of a period, compute the average daily kWh and project it flat across the
  remaining days.

### Acceptance criteria

- [ ] `AgilePredictClient` fetches the 14-day forecast for a given region
- [ ] `agile_forecast` table added via additive schema sync, populated only
      with real (non-tiled) 14-day forecast data
- [ ] Tiling function: given 14-day forecast fixture data and a target date
      well past day 14, produces a sequence where days 15+ correctly repeat
      days 8–14 in order, and terminates correctly (asserted, not just
      assumed, for a long target period)
- [ ] Consumption projection function: given fixture elapsed-period
      consumption data, returns the correct flat daily average
- [ ] An unreachable/error AgilePredict response raises a clear exception
- [ ] Unit tests (`responses`-mocked): a 14-day-cap forecast response, a
      failure/unreachable case; pure-function tests for tiling and
      consumption projection using fixture data
- [ ] Existing test suite remains green

---

## `cost_forecast` table + daily `cost_forecast_refresh` job (#422)

**Blocked by**: #420, #421

**User stories**: 2, 3, 6

### What to build

The integration slice tying the two prior issues together with existing
`consumption`/`agreement`/`product_rate` data to compute and persist both
"this billing period's cost so far" and "total expected cost for this
billing period" in one row per run — this is what makes the pre-existing
`cost_forecast`-reading Grafana panels start returning real numbers.

New table `cost_forecast` (`id`, `billing_period_start`,
`billing_period_end`, `actual_cost_to_date`, `projected_total_cost`,
`computed_at`), added via additive schema sync. Both cost columns are
stored already converted to GBP (`product_rate.unit_rate`/
`standing_charge` are pence/kWh and pence/day — divide by 100 before
persisting, consistent with the `/100` treatment already applied to the
pre-existing live Grafana cost queries).

A `CostForecastRetriever` (constructor DI, Protocol-typed fetch source,
single `refresh()` method — following the `ConsumptionSummaryRetriever`/
`PricingRetriever` shape) that on each run:

1. Fetches billing period boundaries via the Kraken client.
2. Computes `actual_cost_to_date` from `consumption` ⋈ `agreement` ⋈
   `product_rate` for the elapsed portion of the billing period so far.
3. Projects the remaining days' cost:
   - Fixed/variable tariff: the current known `unit_rate` applied for every
     remaining day (no forecasting needed).
   - Agile tariff: the real `AgilePredictClient` forecast plus the tiling
     function (previous issue) for any days beyond the 14-day forecast
     horizon.
   - Future consumption for the remaining days: the consumption-projection
     function (previous issue).
   - **Future tariff assumption**: the account's *current* agreement/product
     is assumed to continue unchanged through `billing_period_end` — a known
     future agreement with a later `valid_from` inside the billing period is
     not checked for or reacted to (a mid-period tariff switch is a rare,
     deliberate customer action; not corrected for).
4. Persists one `cost_forecast` row with `actual_cost_to_date` and
   `projected_total_cost` together.

New daily job `cost_forecast_refresh`, registered via the existing
`register_<x>_job` / `_schedule_refresh_job` / `job_run`-wrapped
background-worker pattern, at the pre-existing (currently unused)
`DAILY_JOB_TIME` constant — explicitly not the hourly cadence used by
consumption/pricing refresh, since billing periods span weeks.

On Kraken or AgilePredict unreachability: log and record a failed
`job_run`, leave the previous `cost_forecast` row in place unchanged
(graceful degradation) rather than writing a partial/corrupt row or
blocking.

### Acceptance criteria

- [ ] `cost_forecast` table added via additive schema sync
- [ ] `CostForecastRetriever.refresh()` computes and persists
      `actual_cost_to_date` and `projected_total_cost` together in one row,
      both already converted to GBP
- [ ] Fixed/variable tariff forecast uses the current known `unit_rate` for
      all remaining days — no `AgilePredictClient` call needed for those
      tariffs
- [ ] Agile tariff forecast uses `AgilePredictClient`'s real 14-day forecast
      plus the tiling function for remaining days beyond day 14
- [ ] Future consumption for remaining days uses the consumption-projection
      function
- [ ] `cost_forecast_refresh` daily job registered at `DAILY_JOB_TIME`,
      following the existing `register_<x>_job`/`_schedule_refresh_job`
      pattern
- [ ] On Kraken or AgilePredict unreachability: `job_run` recorded as a
      failure, and the previous `cost_forecast` row is left unchanged (no
      partial row written)
- [ ] End-to-end test: seeded test-DB session (fixture
      `consumption`/`agreement`/`product_rate` rows, mocked Kraken/
      AgilePredict), asserting the written `cost_forecast` row's
      `actual_cost_to_date` and `projected_total_cost` match expected
      values
- [ ] Edge cases tested: a billing period with a mid-period Agile rate
      change, zero-consumption days, a billing period end date landing well
      beyond the forecast tiling's reach (asserts termination, not just
      absence of a crash)
- [ ] No changes needed to `grafana/mariadb/queries.md` — the panels
      already exist and read from the new table as-is
- [ ] Existing test suite remains green

---

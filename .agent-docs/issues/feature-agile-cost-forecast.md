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

**Blocked by**: #420, #421 (both complete)

**User stories**: 2, 3, 6

### What to build

The integration slice tying the two prior issues together with existing
`consumption`/`agreement`/`product_rate` data to compute and persist both
"this billing period's cost so far" and "total expected cost for this
billing period" in one row per run — this is what makes the pre-existing
`cost_forecast`-reading Grafana panels start returning real numbers.

**Scope**: electricity only. `cost_forecast` has no `energy` column and gas
remains on the existing simple live queries (gas is flat-rate, no
forecasting needed).

New table `cost_forecast` (`id`, `billing_period_start`,
`billing_period_end`, `actual_cost_to_date`, `projected_total_cost`,
`computed_at`), added via additive schema sync. Both cost columns are
stored already converted to GBP (`product_rate.unit_rate`/
`standing_charge` are pence/kWh and pence/day — divide by 100 before
persisting, consistent with the `/100` treatment already applied to the
pre-existing live Grafana cost queries).

New domain types in `data/model.py` (alongside `ConsumptionSummary` — same
"MariaDB-facing app domain" placement, not the Octopus-API-facing
`data/octopus/model.py`): `CostForecast` (billing_period_start,
billing_period_end, actual_cost_to_date, projected_total_cost, computed_at)
and `DailyCostSummary` (date, total_kwh, day_cost_gbp).

**Elapsed-period window**: anchored to midnight UTC of
`billing_period_start` through `now` (UTC) — same anchoring-to-midnight fix
pattern already applied once in this codebase (the yearly-comparison
backfill's `period_from` bug); a non-midnight anchor produces a partial
first day.

**Standing charge correctness**: computed by grouping elapsed consumption
by calendar day and taking `MAX(standing_charge)` *per day*, summed across
all elapsed days — mirroring the existing "Standing Charge vs Unit-Rate
Cost Split" Grafana panel's proven pattern. A single `MAX(standing_charge)`
over the whole multi-day range (like the "Yesterday's Cost" panel does,
correctly, for exactly one day) would silently undercount by charging the
standing fee only once instead of once per elapsed day.

**Data freshness**: reads raw `consumption` ⋈ `agreement` ⋈ `product_rate`
directly, not `daily_consumption_summary`. That table only refreshes on
app startup and weekly (Monday 03:00) — insufficiently fresh for a job that
runs daily; raw `consumption` is refreshed hourly.

**One combined query, not two**: a new `MariaDBClient.read_elapsed_billing_period_costs(period_from, period_to) -> List[DailyCostSummary]`
joins `consumption` ⋈ `agreement` ⋈ `product_rate` once, grouped by day,
returning `(date, total_kwh, day_cost_gbp)` per elapsed day. This correctly
reflects a mid-period Agile rate change too (each half-hour is costed
against whichever `product_rate` row was actually valid at that time, via
the join — no special-casing needed). `actual_cost_to_date` sums
`day_cost_gbp`; the consumption-projection function (issue #421) consumes
the same rows' `total_kwh` — avoids scanning the same consumption rows
twice. A day with zero consumption rows still contributes its standing
charge and a 0-kWh entry to the projection average (not skipped/excluded).

**Current tariff, reused for free**: the electricity meter's *current*
agreement (`valid_to is None`) comes from `MonitoringClient.meters`
(already live-fetched from Octopus on every `refresh_meters()` call) — no
new DB read needed, and it matches the spec's "assume the current
tariff/product continues unchanged through `billing_period_end`" rule
exactly. `Agreement.tariff_type` (already derived via `to_tariff_type()`)
decides the fixed/variable vs. Agile branch below.

A new `MariaDBClient.read_current_product_rate(product_code, region, as_of)`
returns the currently-valid `Rate` (unit_rate + standing_charge) — used for
the fixed/variable remaining-days calculation, and also for the Agile
branch's standing charge (AgilePredict forecasts unit rate only, not
standing charge, so the current known standing charge is held flat across
remaining days regardless of tariff type).

A `CostForecastRetriever` (constructor DI, Protocol-typed
`CostForecastSource(MeterSource, Protocol)` fetch source — following the
`ConsumptionSummaryRetriever`/`PricingRetriever` shape and this project's
established "verb DI seam": narrow one-line delegating methods added to
`MonitoringClient` — `get_current_billing_period`, `fetch_agile_forecast`,
`read_elapsed_billing_period_costs`, `read_current_product_rate`,
`persist_cost_forecast` — so tests wire up real instances with HTTP mocked
via `responses`, never mocking `MariaDBClient` directly) with a single
`refresh()` method that on each run:

1. Fetches billing period boundaries via the Kraken client.
2. Computes `actual_cost_to_date` from the combined elapsed-period query.
3. Determines the current agreement/tariff type from `self._client.meters`.
4. Projects the remaining days' cost:
   - Fixed/variable tariff: the current known `unit_rate` (from
     `read_current_product_rate`) applied for every remaining day — no
     `AgilePredictClient` call at all for these tariffs.
   - Agile tariff: the real `AgilePredictClient` forecast plus the tiling
     function (issue #421) for any days beyond the real forecast horizon,
     filtered to the remaining-days window; standing charge still from
     `read_current_product_rate`.
   - Future consumption for the remaining days: the consumption-projection
     function (issue #421), fed from the combined query's `total_kwh`
     values.
5. Persists one `cost_forecast` row with `actual_cost_to_date` and
   `projected_total_cost` together.

New daily job `cost_forecast_refresh`, registered via the existing
`register_<x>_job` / `_schedule_refresh_job` / `job_run`-wrapped
background-worker pattern, at the pre-existing (currently unused)
`DAILY_JOB_TIME` constant — explicitly not the hourly cadence used by
consumption/pricing refresh, since billing periods span weeks.

On Kraken or AgilePredict unreachability (including the very first-ever
run, before any row exists): log and record a failed `job_run`, write no
row at all — leaving any previously-existing `cost_forecast` row unchanged
(graceful degradation) rather than writing a partial/corrupt row or
blocking. On the first-ever run there is nothing to fall back to, so the
Grafana panels simply show no data until the first successful run — an
honest reflection of state, not a fabricated placeholder.

### Given-When-Then scenarios (Three Amigos, agreed)

1. **Fixed/variable tariff, elapsed days present** — `actual_cost_to_date`
   reflects real per-day unit-rate cost + standing charge; `projected_total_cost`
   extrapolates remaining days at the current known rate.
2. **Agile tariff, remaining days within the real forecast horizon** — uses
   AgilePredict's real half-hourly rates.
3. **Agile tariff, remaining days beyond the forecast horizon** — tiling
   (issue #421) fills the gap.
4. **Mid-period rate change during the elapsed portion** —
   `actual_cost_to_date` correctly reflects each half-hour's actually-
   applicable historical rate via the join, not a single flat rate.
5. **Zero-consumption day** — still contributes its standing charge and
   counts as a 0-kWh day in the projection average.
6. **Kraken unreachable** — no row written, `job_run` failure, previous row
   (if any) untouched.
7. **AgilePredict unreachable (Agile tariff only)** — same graceful
   degradation.
8. **Fixed/variable tariff never calls AgilePredict** — no wasted call, no
   unrelated failure mode for tariffs that don't need forecasting.
9. **Daily job registration** — `cost_forecast_refresh` scheduled at
   `DAILY_JOB_TIME` via the existing `register_<x>_job` pattern.
10. **First-ever run failure** — no row written (nothing to fall back to),
    `job_run` records failure.

### Acceptance criteria

- [ ] `cost_forecast` table added via additive schema sync
- [ ] `CostForecast`/`DailyCostSummary` domain types added to `data/model.py`
- [ ] `MariaDBClient.read_elapsed_billing_period_costs` joins
      `consumption`⋈`agreement`⋈`product_rate`, grouped by day, taking
      `MAX(standing_charge)` per day (not over the whole range)
- [ ] `MariaDBClient.read_current_product_rate` returns the currently-valid
      rate for a product/region
- [ ] `CostForecastRetriever.refresh()` computes and persists
      `actual_cost_to_date` and `projected_total_cost` together in one row,
      both already converted to GBP
- [ ] Elapsed window anchored to midnight UTC of `billing_period_start`
- [ ] Current tariff/agreement sourced from `self._client.meters`, not a
      new DB read
- [ ] Fixed/variable tariff forecast uses the current known `unit_rate` for
      all remaining days — no `AgilePredictClient` call needed for those
      tariffs
- [ ] Agile tariff forecast uses `AgilePredictClient`'s real forecast plus
      the tiling function for remaining days beyond the real horizon;
      standing charge still from `read_current_product_rate`
- [ ] Future consumption for remaining days uses the consumption-projection
      function, fed from the combined query's `total_kwh` values
- [ ] `cost_forecast_refresh` daily job registered at `DAILY_JOB_TIME`,
      following the existing `register_<x>_job`/`_schedule_refresh_job`
      pattern
- [ ] On Kraken or AgilePredict unreachability (including the first-ever
      run): `job_run` recorded as a failure, no row written, any prior row
      left unchanged
- [ ] All 10 Given-When-Then scenarios above have a corresponding test
- [ ] End-to-end test: seeded test-DB session (fixture
      `consumption`/`agreement`/`product_rate` rows, mocked Kraken/
      AgilePredict), asserting the written `cost_forecast` row's
      `actual_cost_to_date` and `projected_total_cost` match expected
      values
- [ ] No changes needed to `grafana/mariadb/queries.md` — the panels
      already exist and read from the new table as-is
- [ ] Existing test suite remains green

---

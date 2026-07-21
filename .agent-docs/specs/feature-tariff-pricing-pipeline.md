# Tariff Pricing Pipeline

## Problem Statement

The app tracks consumption but has no idea what anything actually costs. `PricingRetriever` is an unimplemented stub, and the `tariff`/`cost` tables it was meant to populate are dead schema nothing writes to. Every downstream cost feature — dashboard cost panels, tariff comparison, cost forecasting — is blocked on this.

## Solution

Implement the real pricing pipeline: fetch Octopus's published product catalogue and rates for the account's region, persist which product the account's meter is actually on (`agreement`), and store rates uniformly for every product (`product_rate`) so actual cost can be computed by a simple join against consumption.

## User Stories

1. As the operator, I want the app to record which Octopus product/tariff my meter is actually on for each period, so that actual cost can be computed without hardcoding "I'm on Agile."
2. As the operator, I want the app to fetch and store half-hourly Agile rates for my region, so that my actual electricity cost reflects real dynamic pricing.
3. As the operator, I want the app to fetch and store rates for other published Octopus domestic electricity products in my region, so that a later comparison feature has real data to compare against.
4. As the operator, I want gas rates stored the same way as electricity (even though gas pricing is flatter), so that gas cost is computed consistently.
5. As a developer, I want actual cost to be computable via a simple join (consumption ⋈ agreement ⋈ product_rate), so that cost panels and future features don't duplicate pricing logic.

## Implementation Decisions

- New tables, added to `mariadb/init.sql` and `app/data/mysql/sql_models.py`:
  - `agreement(id, energy, product_code, tariff_code, valid_from, valid_to)`
  - `product(product_code PK, display_name, direction)`
  - `product_rate(id, product_code, region, valid_from, valid_to, unit_rate, standing_charge)`
  - The existing unused `tariff`/`cost` tables are dropped — a clean-slate schema rewrite is acceptable (no live data to migrate, no migration tooling required).
- `app/data/pricing.py`: implement `PricingRetriever`, mirroring `ConsumptionRetriever`'s shape. `refresh()` orchestrates:
  1. Sync the account's current `Agreement` (from `MonitoringClient.account`/`meters`) into `agreement`.
  2. Fetch the product catalogue for the account's region and persist to `product`.
  3. Fetch rates for the account's own product(s) and persist to `product_rate`.
- `app/data/octopus/api.py`: implement the currently-commented-out pricing endpoints — product list (`GET /v1/products/`), product/region availability, and unit-rate/standing-charge endpoints for electricity (half-hourly for Agile, coarser for other tariff types) and gas.
- `app/data/mysql/client.py`: add `write_agreement`, `write_product`, `write_product_rate`, following the existing `upsert`/`session_write_scope` pattern used by `write_consumption`.
- Wire `PricingRetriever.refresh()` into the scheduler (using the `job_run`-wrapped mechanism from `chore/operational-hygiene`) on the same cadence as consumption refresh, plus a startup call analogous to `ConsumptionRetriever.retrieve()`.
- Region code: already available via `MonitoringClient.region_code` — reuse rather than re-deriving.

## Testing Decisions

- HTTP boundary: mock Octopus product/rate endpoints with `responses`; assert `PricingRetriever` parses and writes the expected rows.
- DB boundary: SQLite in-memory session, asserting `agreement`/`product`/`product_rate` rows via the new client write methods, including upsert-on-conflict behaviour (mirroring existing coverage expectations for `write_consumption`).
- Cost-from-join is exercised as a query-level integration test (seeded SQLite/test MariaDB, assert the join produces the expected total cost for known fixture consumption + rates) rather than unit-testing SQL string construction.
- Edge cases: a product with no published rate for the account's region (skip, log, don't crash); gaps in Agile half-hourly rates; tariff types not yet supported by rate-fetching (e.g. fixed/prepay) — explicitly unhandled for now, matching the existing `TariffType` detection gap.

## Out of Scope

Cost forecasting (`feature/agile-cost-forecast`). Any dashboard changes (`feature/grafana-dashboard`). Export/Outgoing Octopus tariffs (declined during the design session).

## Further Notes

This is the foundational data-pipeline branch that `feature/agile-cost-forecast` builds on. See **Agreement** and **Product / Product Rate** in `.agent-docs/context.md`, and `grafana/mariadb/queries.md` for how these tables are expected to be queried downstream.

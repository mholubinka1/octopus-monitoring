# Issues: feature-tariff-pricing-pipeline

## Pricing schema (#379)

**Blocked by**: None

**User stories**: 1, 2, 3, 4, 5 (foundational)

### What to build

Add the new `agreement`, `product`, and `product_rate` tables to `mariadb/init.sql` and
`app/data/mysql/sql_models.py`, matching the shapes described in the spec
(`agreement(id, energy, product_code, tariff_code, valid_from, valid_to)`,
`product(product_code PK, display_name, direction)`,
`product_rate(id, product_code, region, valid_from, valid_to, unit_rate, standing_charge)`).
Drop the existing unused `tariff` and `cost` tables from both files — a clean-slate schema
rewrite is acceptable since nothing currently writes to them and there is no live data to
migrate. No application behaviour changes in this slice; it only lands the schema so later
slices can write to it.

### Acceptance criteria

- [x] `mariadb/init.sql` defines `agreement`, `product`, `product_rate`; `tariff` and `cost` are dropped
- [x] `app/data/mysql/sql_models.py` has matching SQLAlchemy models; `tariff`/`cost` model classes removed
- [x] `docker-compose up` brings up MariaDB cleanly against the new schema
- [x] Existing test suite remains green

---

## Persist the account's current agreement (#380)

**Blocked by**: #379 (Pricing schema)

**User stories**: 1

### What to build

Implement `MariaDBClient.write_agreement`, following the existing `upsert`/`session_write_scope`
pattern used by `write_consumption`. Implement `PricingRetriever.refresh()` orchestration step 1:
sync the account's current `Agreement` (already available in-memory via
`MonitoringClient.meters[*].agreements`) into the `agreement` table for each meter. Wire
`PricingRetriever` into the scheduler in `main.py`, using the `job_run`-wrapped mechanism from
`chore/operational-hygiene`, on the same cadence as consumption refresh, plus a startup call
analogous to `ConsumptionRetriever.retrieve()`. This slice establishes the retriever/orchestration
scaffold that later slices extend with additional `refresh()` steps.

### Acceptance criteria

- [x] `write_agreement` persists `id`/`energy`/`product_code`/`tariff_code`/`valid_from`/`valid_to` with upsert-on-conflict behaviour
- [x] `PricingRetriever.refresh()` writes each meter's current agreement to the DB
- [x] `PricingRetriever` is wired into the scheduler with `job_run` tracking, plus a startup call in `main.py`
- [x] Unit tests: DB boundary (SQLite in-memory) for `write_agreement` including upsert-on-conflict; `PricingRetriever` writes expected rows for a mocked meter/agreement fixture

---

## Fetch and persist the product catalogue for the account's region (#381)

**Blocked by**: #380 (Persist the account's current agreement)

**User stories**: 3 (catalogue half)

### What to build

Implement the product catalogue endpoints in `app/data/octopus/api.py`: `GET /v1/products/` and
product/region availability. Implement `MariaDBClient.write_product`. Extend
`PricingRetriever.refresh()` with orchestration step 2: fetch the product catalogue for the
account's region (`MonitoringClient.region_code` — reuse, don't re-derive) and persist to
`product`.

### Acceptance criteria

- [x] `api.py` has product-catalogue and region-availability fetch methods, with HTTP-mocked tests via `responses`
- [x] `write_product` upserts `product_code`/`display_name`/`direction`
- [x] `PricingRetriever.refresh()` persists the fetched catalogue for the account's region
- [x] Unit tests: HTTP boundary (mocked Octopus responses) and DB boundary (SQLite) for the new write path

---

## Fetch and persist Agile electricity rates for the account's own product (#382)

**Blocked by**: #381 (Fetch and persist the product catalogue for the account's region)

**User stories**: 2

### What to build

Implement the electricity unit-rate/standing-charge endpoints in `api.py` (half-hourly granularity
for Agile; coarser for other tariff types where applicable). Implement
`MariaDBClient.write_product_rate`, following the existing upsert pattern. Extend
`PricingRetriever.refresh()` with orchestration step 3: fetch rates for the account's own
electricity product/tariff and persist to `product_rate`.

### Acceptance criteria

- [x] `api.py` has electricity rate-fetch methods (half-hourly for Agile), with HTTP-mocked tests
- [x] `write_product_rate` upserts `id`/`product_code`/`region`/`valid_from`/`valid_to`/`unit_rate`/`standing_charge` with upsert-on-conflict behaviour
- [x] `PricingRetriever.refresh()` persists the account's own-product electricity rates
- [x] Edge case handled without crash: gaps in Agile half-hourly rates
- [x] Unit tests: HTTP boundary and DB boundary (including upsert-on-conflict, mirroring `write_consumption` coverage)

---

## Fetch and persist rates for other published electricity products (#383)

**Blocked by**: #382 (Fetch and persist Agile electricity rates for the account's own product)

**User stories**: 3 (comparison half)

### What to build

Extend the rate-fetching mechanism built in the previous slice so `PricingRetriever.refresh()`
fetches and persists rates for every catalogued electricity product for the account's region —
not just the account's own product — so `product_rate` uniformly holds comparison data for a
later tariff-comparison feature.

### Acceptance criteria

- [x] `PricingRetriever.refresh()` fetches and persists rates for every catalogued electricity product/region combination
- [x] Edge case handled without crash: a product with no published rate for the account's region — skip and log
- [x] Edge case handled without crash: tariff types not yet supported by rate-fetching (e.g. fixed/prepay) — explicitly unhandled, matching the existing `TariffType` detection gap
- [x] Unit tests cover the skip/no-rate path and the unsupported-tariff-type path

---

## Fetch and persist gas rates (#384)

**Blocked by**: #382 (Fetch and persist Agile electricity rates for the account's own product)

**User stories**: 4

### What to build

Implement the gas unit-rate/standing-charge endpoints in `api.py` (coarser than electricity's
half-hourly granularity). Extend `PricingRetriever.refresh()` to persist gas rates for the
account's own product the same way as electricity. Full-catalogue gas comparison is not required —
only electricity comparison is in scope per the spec's user stories.

### Acceptance criteria

- [x] `api.py` has gas rate-fetch methods, with HTTP-mocked tests
- [x] `PricingRetriever.refresh()` persists gas rates for the account's own product
- [x] Unit tests assert gas rows are written in the same shape/pattern as electricity rows

---

## Cost-via-join integration test (#385)

**Blocked by**: #383 (Fetch and persist rates for other published electricity products), #384 (Fetch and persist gas rates)

**User stories**: 5

### What to build

Add a query-level integration test (seeded SQLite in-memory or test MariaDB) that joins
`consumption ⋈ agreement ⋈ product_rate` for known fixture data and asserts the computed total
cost matches the expected value, for both electricity and gas. This validates that actual cost is
computable via a simple join without duplicating pricing logic in application code — no new
production code is expected beyond the join query itself.

### Acceptance criteria

- [x] Integration test seeds `consumption`, `agreement`, and `product_rate` fixtures
- [x] Test asserts the join produces the expected total cost for a known electricity fixture
- [x] Test asserts the join produces the expected total cost for a known gas fixture

---

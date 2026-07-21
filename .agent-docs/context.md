# Octopus Monitoring

A scheduled worker that polls the Octopus Energy API for a UK household's electricity and gas consumption, normalizes it, and persists it to MariaDB for downstream visualization (e.g. Grafana).

## Language

### Octopus Energy Domain

**MPAN**:
Meter Point Administration Number — the unique identifier for an electricity meter point.
_Avoid_: electricity meter ID, meter number

**MPRN**:
Meter Point Reference Number — the unique identifier for a gas meter point.
_Avoid_: gas meter ID, meter number

**Meter Point**:
The abstract connection point for a fuel supply, represented in code as `Electricity` or `Gas`, both subclasses of `Meter`.
_Avoid_: meter, supply point

**Agreement**:
A tariff contract period held against a meter, carrying a tariff code, product code, validity dates, and price history.
_Avoid_: contract, plan

**Tariff Code / Product Code**:
Octopus's identifiers for a pricing plan; the product code is derived from the tariff code by regex.
_Avoid_: plan ID, rate code

**Tariff Type**:
The classification of a pricing plan — `variable`, `economy7`, `agile`, `fixed`, or `prepay`. Only `economy7` and `agile` are currently detected in code.
_Avoid_: plan type, rate type

**Agile**:
Octopus's half-hourly dynamic electricity pricing tariff, detected via tariff code containing `AGILE`. Its rates are fetched and stored through the same generic path as every other product (see `PricingRetriever`); a dedicated Agile cost forecast feature is still unbuilt (see Cost and Forecasting below).
_Avoid_: dynamic tariff, agile octopus

**Standing Charge**:
The fixed daily charge component of a tariff. Modelled in `Price`/`Rate` and persisted per product/region in the `product_rate` table by `PricingRetriever`.
_Avoid_: daily charge, base fee

**Unit Rate**:
The per-kWh price component of a tariff. Same storage path as standing charge.
_Avoid_: price per unit, rate

**Consumption**:
A single metered usage record for a time interval: raw value, unit, and an estimated kWh figure.
_Avoid_: usage, reading

**Estimated kWh (`est_kwh`)**:
Consumption normalized to kWh. For gas this applies a volume correction factor (1.02264) and calorific value (39.5) to convert from m³.
_Avoid_: normalized usage, kwh value

**Region Code / GSP**:
The Grid Supply Point code for a geographic distribution zone, looked up from postcode; required to select region-specific tariff pricing.
_Avoid_: zone, area code

**Account**:
An Octopus Energy account — holds an account number, address, and postcode, and can have multiple meters.
_Avoid_: customer, user

### Data Storage

**MariaDB `octopus` database**:
The sole active persistence store for this app. The database itself is created by `mariadb/init.sql`; every table inside it is defined solely by `app/data/mysql/model.py` (see **Schema Sync**) and includes `consumption`, `agreement`, `product`, `product_rate`, and `job_run`.
_Avoid_: the database, mysql db

**Schema Sync**:
The additive-only schema reconciliation `MariaDBClient` runs automatically on every app startup — creates any table missing from the live database and adds any column missing from an existing table, both diffed against `model.py`. Never drops or alters an existing column; that stays a deliberate manual action. See [ADR-0005](adr/0005-additive-only-schema-sync.md).
_Avoid_: migration, schema migration (this project deliberately has no versioned migration tool)

**InfluxDB (legacy)**:
A former time-series store, described historically in the README; its implementation (`app/_deprecated/`) has been removed entirely — MariaDB is, and has been, the only active sink.
_Avoid_: the time-series DB (when referring to the current system)

### Scheduling and Retrieval

**Startup Backfill**:
The historical consumption retrieval run on every process start, bounded by `retention_days` (default 400) — not one-time: `ConsumptionRetriever`'s last-retrieved watermark is in-memory only, so this re-runs in full on every restart, not just the first ever run.
_Avoid_: initial sync, bootstrap, one-time sync

**Refresh Loop**:
The recurring poll of the Octopus API, driven by the `schedule` library on the configured `refresh_interval_hours`.
_Avoid_: polling loop, cron job

**`ConsumptionRetriever`**:
Orchestrates paginated consumption retrieval from Octopus and writes it to MariaDB, tracking the last-retrieved timestamp per energy type.
_Avoid_: consumption service

**`PricingRetriever`**:
Orchestrates syncing agreements, the product catalogue, the account's own product rates, and comparison rates for every other available product, writing all of it to MariaDB via `PricingSource`.
_Avoid_: pricing service

**`MonitoringClient`**:
The top-level facade wiring the Octopus API client and MariaDB client together; holds account/meter state for a run.
_Avoid_: app client, main client

### Cost and Forecasting

**Billing Period**:
The current invoice cycle for an account. Fetched from Octopus's GraphQL "Kraken" API (`account.billingOptions`), authenticated by exchanging the account's existing REST API key for a short-lived JWT via `obtainKrakenToken` — not available via the REST v1 API this app otherwise uses. For accounts on flexible billing (`isFixed: false`, no `currentBillingPeriodEndDate` from Octopus), the period end is assumed to be one calendar month after the period start, same day-of-month, clamped to the last valid day if that day doesn't exist in the target month. See `.agent-docs/research/octopus-billing-period-api.md`.
_Avoid_: billing cycle, invoice period

**Product / Product Rate**:
`Product` is Octopus's public catalogue entry for a tariff plan, distinct from `Agreement` (the account's actual contract). `Product Rate` is a product's unit rate and standing charge for a region and time period — stored uniformly for every product, including whichever one the account is actually on, so actual cost and the price-curve panel read from the same table.
_Avoid_: tariff (when referring to the public catalogue rather than the account's own agreement)

**Actual Cost**:
Cost computed directly from real consumption × the real rates actually charged (`consumption` ⋈ `agreement` ⋈ `product_rate`) — covers "yesterday's cost" (no billing-period dependency) and "this billing period's cost so far" (needs the billing period start, so computed and persisted by the app rather than a pure live query).
_Avoid_: spend, actual spend

**Cost Forecast**:
A projection of total cost for the current billing period, built from actual cost to date plus a forecast for the remaining days: future consumption estimated as the average daily usage of the billing period so far, and future price sourced from Agile Predict's real 14-day forecast, tiled (the last 7 forecast days repeated in sequence) for any remaining days beyond that 14-day horizon.
_Avoid_: price forecast (that term refers to the underlying Agile price data, not the derived cost projection)

**Agile Predict**:
A third-party public service (`agilepredict.com`, backed by the same Fly.io app historically documented at `prices.fly.dev` — that domain's `/v2/<region>/` path now serves the HTML frontend, not JSON) providing a hard-capped 14-day-ahead Agile price forecast per GSP region via `GET https://agilepredict.com/api/{region}/`, no authentication required. Consumed as an external API rather than reimplemented in-house — see `.agent-docs/adr/0002-agile-predict-forecast-dependency.md`.
_Avoid_: the forecast API, prediction service

**Job Run**:
A logged execution record (job name, status, timestamp) for each scheduled job — consumption refresh, pricing refresh, cost forecast refresh — used to drive the dashboard's health/staleness panel.
_Avoid_: job log, task run

**Retention Window**:
The intended 400-day period after which raw consumption and product-rate rows are meant to be pruned by a daily job — that pruning job is not yet implemented, so nothing is actually deleted today. `retention_days` (default 400) currently only bounds the Startup Backfill's lookback. Derived/aggregated results (e.g. `cost_forecast`) are not subject to pruning once it exists. See `.agent-docs/adr/0003-90-day-data-retention.md`.
_Avoid_: data expiry, TTL

**Cheap Window**:
The cheapest contiguous block of a given duration (30min/1h/2h/3h/4h/6h) within today's or tomorrow's Agile half-hourly rates, computed live at query time rather than stored.
_Avoid_: best time to use power, price dip

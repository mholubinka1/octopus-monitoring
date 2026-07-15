# Grafana Dashboard

## Problem Statement

All the data being collected and computed — consumption, actual cost, tariff comparison, forecasts — has nowhere to be seen. There is no working dashboard today; the README's InfluxDB/Grafana story is dead code (see [ADR-0001](../adr/0001-mariadb-over-influxdb.md)).

## Solution

Build a single Grafana dashboard, provisioned from the repo, reading directly from MariaDB, laid out cost-first across four rows (Cost Summary, Electricity, Gas, Health), using the queries already drafted in `.agent-docs/grafana-queries.md`.

## User Stories

1. As the account holder, I want to open one dashboard and see today's, month-to-date, and projected month-end electricity cost at a glance, so that cost is the first thing I see, not raw consumption numbers.
2. As the account holder, I want to see the half-hourly Agile price curve (actual + forecast) alongside my consumption and cost, so that I understand why a given day cost what it did.
3. As the account holder, I want to see whether Agile is still the cheapest option and by how much, so that the tariff-comparison work is actually visible, not just computed and forgotten in the database.
4. As the account holder, I want day-of-week, rolling-average, and heatmap views of my usage over the last 12 weeks, so that I can spot patterns without manually querying the database.
5. As the operator, I want a health panel showing the last successful run of each scheduled job and whether `prices.fly.dev` is reachable, so that a silent failure becomes visible without checking logs.
6. As the account holder, I want gas tracked with simple consumption/cost panels, so that gas isn't ignored even though it doesn't get the full tariff-comparison treatment.

## Implementation Decisions

- Grafana dashboard provisioned as JSON and checked into the repo (e.g. `grafana/dashboards/octopus-monitoring.json`), following the provisioning convention already established in the sibling `pi-desktop/monitoring` repo for consistency across the user's home infrastructure. A MySQL/MariaDB data source is configured against the `octopus` database.
- Dashboard variables: `${region}` (GSP region code) and `${variable_product_code}` (comparison baseline product — manually maintained, see `.agent-docs/grafana-queries.md`).
- Panels and queries as specified in `.agent-docs/grafana-queries.md` — that document is the source of truth for query SQL; this spec wires them into actual Grafana panels with the visualization types already annotated per panel (stat, time series, bar gauge, heatmap, table).
- Row layout: Cost Summary → Electricity → Gas → Health, per the design session (cost-first, single dashboard with row-based sections rather than separate dashboards).
- `docker-compose.yml`: add a `grafana` service (image, volumes for dashboard provisioning + `grafana.ini`), matching the pattern used in `pi-desktop/monitoring/docker-compose.yml`.

## Testing Decisions

- New integration test: seed a test MariaDB instance (a real MariaDB test service is required — several queries use MariaDB-specific window-function and date syntax that may not run identically on SQLite) with fixture rows across `consumption`, `agreement`, `product_rate`, `tariff_comparison_result`, `agile_forecast`, `daily_saving`, and `job_run`. Execute every query from `grafana-queries.md` against it and assert each returns without error and with the expected shape/values for at least one representative panel per row.
- No unit tests for the Grafana JSON provisioning itself — not business logic. Visual verification (open the dashboard, confirm panels render with real data) is the acceptance check, consistent with "act as the first line of behaviour verification" in `.agent-docs/agent.md`.

## Out of Scope

Alerting or push notifications — logs/dashboard-only was the explicit decision from the design session. Any new data-producing logic — this spec only wires up presentation of data produced by the three preceding feature specs.

## Further Notes

Depends on `chore/operational-hygiene` (health data), `feature/tariff-pricing-pipeline` (cost data), `feature/cheapest-tariff-comparison` (comparison data), and `feature/agile-cost-forecast` (forecast/savings data) all being merged first. Treat `.agent-docs/grafana-queries.md` as the query-level spec for this branch, but validate its assumed schema against what actually got built in the three data specs before wiring panels — the queries were drafted before those specs' Implementation Decisions were finalized, so some field/table names may have shifted slightly.

# Grafana Dashboard

## Problem Statement

All the data being collected and computed — consumption, actual cost, cost forecast — has nowhere to be seen. There is no working dashboard today; the README's InfluxDB/Grafana story is dead code (see [ADR-0001](../adr/0001-mariadb-over-influxdb.md)).

## Solution

Build a single Grafana dashboard, provisioned from the repo, reading directly from MariaDB, laid out cost-first across four rows (Cost Summary, Electricity, Gas, Health), using the queries drafted in `grafana/mariadb/queries.md`.

## User Stories

1. As the account holder, I want to open one dashboard and see yesterday's, this-billing-period's, and total-expected cost at a glance, so that cost is the first thing I see, not raw consumption numbers.
2. As the account holder, I want to see the half-hourly Agile price curve (actual + forecast) alongside my consumption and cost, so that I understand why a given day cost what it did.
3. As the account holder, I want day-of-week, rolling-average, and heatmap views of my usage over the last 12 weeks, so that I can spot patterns without manually querying the database.
4. As the operator, I want a health panel showing the last successful run of each scheduled job and whether AgilePredict/Kraken are reachable, so that a silent failure becomes visible without checking logs.
5. As the account holder, I want gas tracked with simple consumption/cost panels, so that gas isn't ignored even though it doesn't get any cost-forecast treatment.

## Implementation Decisions

- Grafana dashboard provisioned as JSON and checked into the repo (`grafana/dashboards/octopus-monitoring.json`), following the provisioning convention already established in the sibling `pi-desktop/monitoring` repo. A MySQL/MariaDB data source is configured against the `octopus` database.
- Dashboard variable: `${region}` (GSP region code) only. The old `${variable_product_code}` comparison-baseline variable is dropped along with the tariff-comparison feature it existed for.
- Panels and queries as specified in `grafana/mariadb/queries.md` — that document is the source of truth for query SQL; this spec wires them into actual Grafana panels with the visualization types already annotated per panel (stat, time series, bar gauge, heatmap, table).
- Row layout: Cost Summary → Electricity → Gas → Health, cost-first, single dashboard with row-based sections rather than separate dashboards.
- `docker-compose.yml`: add a `grafana` service (image, volumes for dashboard provisioning + `grafana.ini`), matching the pattern used in `pi-desktop/monitoring/docker-compose.yml`.

## Testing Decisions

- New integration test: seed a test MariaDB instance (a real MariaDB test service is required — several queries use MariaDB-specific window-function and date syntax that may not run identically on SQLite) with fixture rows across `consumption`, `agreement`, `product_rate`, `cost_forecast`, and `job_run`. Execute every query from `grafana/mariadb/queries.md` against it and assert each returns without error and with the expected shape/values for at least one representative panel per row.
- No unit tests for the Grafana JSON provisioning itself — not business logic. Visual verification (open the dashboard, confirm panels render with real data) is the acceptance check, consistent with "act as the first line of behaviour verification" in `.agent-docs/agent.md`.

## Out of Scope

- Alerting or push notifications — logs/dashboard-only was the explicit decision from the original design session.
- Any new data-producing logic — this spec only wires up presentation of data produced by `feature/tariff-pricing-pipeline` (already built) and `feature/agile-cost-forecast` (reconciled spec, not yet built).
- Any tariff-comparison panel ("Cheapest Tariff Saving," "Tariff Comparison Detail," cumulative Agile-vs-Variable savings) — these existed only for the now-dropped comparison feature and are removed from scope entirely, not deferred.

## Further Notes

Depends on `chore/operational-hygiene` (health data), `feature/tariff-pricing-pipeline` (cost data, already merged), and `feature/agile-cost-forecast` (forecast data — reconciled spec, not yet built) all being merged first. No longer depends on `feature/cheapest-tariff-comparison` (deleted). Treat `grafana/mariadb/queries.md` as the query-level spec for this branch, but validate its assumed schema against what actually gets built in `feature/agile-cost-forecast` before wiring panels.

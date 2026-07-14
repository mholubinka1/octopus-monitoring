# Energy Monitoring

This application polls the Octopus Energy API for electricity and gas consumption and
writes it to a MariaDB database, where it can be queried and visualised using Grafana's
native MySQL data source.

Cheapest-tariff comparison and cost forecasting are planned but not yet implemented —
see `.agent-docs/specs/` for the roadmap.

## Architecture

- **`app/`** — polls the Octopus API on a configurable interval and writes consumption
  readings to MariaDB (`data.consumption.ConsumptionRetriever` /
  `data.mysql.client.MariaDBClient`).
- **MariaDB** — the persistence layer (see `mariadb/init.sql` for the schema).
- **Grafana** (not included in this repo) — point its MySQL data source at the MariaDB
  instance to build dashboards.

## Configuration

### Application

Create `config.yml` from `config.yml.template`, providing:

- Your Octopus API key and account number, [available from your Octopus dashboard](https://octopus.energy/dashboard/new/accounts/personal-details/api-access).
- MariaDB connection details (`host`, `port`, `database`, `username`, `password`).
- Data refresh settings: `refresh_interval_hours` (how often consumption is polled) and
  `historical_limit_days` (how far back to backfill on startup).

### Docker Compose

Create `.env` from `.env.template`, providing the MariaDB root/user credentials used to
initialise the database container.

## Running

```
docker compose up
```

This starts the `mariadb` container and the `energy-monitor` app container (built from
the published `mholubinka1/octopus-monitoring` image), which connects to MariaDB once it
reports healthy. The compose file's bind-mount paths are host-specific — edit them for
your own deployment.

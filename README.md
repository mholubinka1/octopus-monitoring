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
- **MariaDB** — the persistence layer. Schema lives solely in `app/data/mysql/model.py`;
  `data.mysql.client.MariaDBClient` syncs it into the live database automatically on every
  app startup (creating missing tables/columns only — see
  `.agent-docs/adr/0005-additive-only-schema-sync.md`).
- **Grafana** (not included in this repo) — point its MySQL data source at the MariaDB
  instance to build dashboards.

## Configuration

### Application

Create `config.yml` from `config.yml.template`, providing:

- Your Octopus API key and account number, [available from your Octopus dashboard](https://octopus.energy/dashboard/new/accounts/personal-details/api-access).
- MariaDB connection details (`host`, `port`, `database`, `username`, `password`).
  **`database` must be `octopus`** — `docker-compose.yml` hardcodes that name for the
  database MariaDB actually creates, so any other value here means the app can never
  connect to a database that exists.
- Data refresh settings: `refresh_interval_hours` (how often consumption is polled) and
  `retention_days` (how far back to backfill on every startup — also the intended data
  retention window, see [ADR-0003](.agent-docs/adr/0003-90-day-data-retention.md); no
  persisted watermark means this backfill re-runs in full on every restart, not just
  the first one).

### Docker Compose

Create `.env` from `.env.template`, providing `MARIADB_USER`/`MARIADB_PASSWORD` — the
credentials for the app's own MariaDB user. **These must match `config.yml`'s
`mariadb.username`/`password` exactly** — the two files aren't automatically kept in
sync. Docker Compose passes these values into the `mariadb` container on every start,
but MariaDB's own entrypoint only *acts* on them once — when it initializes an empty
data directory, to create that user. On a container restart against an
already-initialized data volume, MariaDB ignores them for user creation; editing `.env`
afterwards will not rotate the existing MariaDB user's password. See
[ADR-0006](.agent-docs/adr/0006-minimal-env-file-over-config-yml-only.md) for why this
one small overlap remains rather than being engineered away. `MARIADB_DATABASE` and
`MARIADB_RANDOM_ROOT_PASSWORD` are not in `.env` — they're hardcoded directly in
`docker-compose.yml`, since neither is a secret.

## Running

### First-time deployment

1. **Edit the bind-mount paths.** `docker-compose.yml`'s `volumes:` entries
   (`/mnt/media/pi-media/monitoring/...`) are host-specific placeholders — change them
   to real paths on your machine before doing anything else. You need four host
   directories/files:
   - a config directory for the app (mounted to `/config`)
   - a log directory for the app (mounted to `/log`)
   - a data directory for MariaDB (mounted to `/var/lib/mysql`)
   - the repo's `mariadb/init.sql` copied to a path on the host (mounted read-only to
     `/docker-entrypoint-initdb.d/init.sql`)
2. **Create `config.yml`** from `config.yml.template` (see Configuration above) and
   place it at the path you chose for the app's config bind mount.
3. **Create `.env`** from `.env.template` in the same directory as `docker-compose.yml`,
   filling in `MARIADB_USER`/`MARIADB_PASSWORD` to match the values you put in
   `config.yml`.
4. **Start the stack:**

   ```bash
   docker compose up -d
   ```

   On first run, MariaDB initializes its (empty) data directory: it creates the
   `octopus` database (via the mounted `init.sql`) and the app's MariaDB user (via the
   `.env` credentials), then reports healthy. The `energy-monitor` container waits for
   that healthcheck before starting, connects, runs its additive schema sync (creating
   every table from scratch — see
   [ADR-0005](.agent-docs/adr/0005-additive-only-schema-sync.md)), and begins polling.
5. **Verify it worked:**

   ```bash
   docker compose logs -f energy-monitor
   ```

   Look for the settings-loaded and schema-sync log lines, followed by consumption
   retrieval starting. `docker compose ps` should show both containers `Up` (`mariadb`
   as `healthy`).

### Subsequent deployments (updates, restarts, redeploys)

- **New image version**: `docker compose pull && docker compose up -d` — the
  `mariadb` data directory already exists, so `.env` is not re-read; the app container
  is simply replaced and re-runs its (idempotent, additive-only) schema sync against
  the existing database on startup. `watchtower` (see the compose file's
  `com.centurylinklabs.watchtower.enable` label) does this automatically on its own
  schedule if it's running on the host — a manual `docker compose pull` is only needed
  for an out-of-schedule update.
- **Config changes** (`config.yml`, e.g. `refresh_interval_hours`): edit the file, then
  `docker compose restart energy-monitor` — no rebuild or pull needed.
- **Changing the MariaDB app user's password**: editing `.env` alone does **not**
  change it on an already-initialized database — you'd need to update the password in
  MariaDB directly (e.g. `ALTER USER`) and in `config.yml` together. `.env` only
  matters again if the data volume is wiped and MariaDB re-initializes from empty.
- **A brand new table/column** added by a future feature: no manual DDL step needed —
  the schema sync creates it automatically on the next `energy-monitor` startup.

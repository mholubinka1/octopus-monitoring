# Schema Sync: Add Missing Indexes

## Problem Statement

Every query that joins `consumption` → `agreement` → `product_rate` on the `valid_from`/`valid_to` half-open window — the documented convention used throughout `grafana/mariadb/queries.md` and by `MariaDBClient.read_elapsed_billing_period_costs` in production — runs as a full table scan with a Block Nested Loop join. Confirmed via `EXPLAIN` against production: `consumption` (18,028 rows), `agreement` (7 rows), and `product_rate` (36,720 rows) all show `type=ALL`, `possible_keys=NULL`. Root cause: no table in `app/data/mysql/model.py` declares any index beyond its primary key, and `MariaDBClient._sync_schema` only auto-creates missing tables and missing columns — it has no mechanism for indexes at all. This isn't just a slow Grafana dashboard: it's the same unindexed join the `cost_forecast_refresh` job runs against production every day.

## Solution

Declare the missing indexes as SQLAlchemy `Index()` objects on the affected models, then extend `MariaDBClient._sync_schema` to diff declared indexes against `inspector.get_indexes()` and `CREATE INDEX` anything missing — the same additive-only, idempotent pattern ADR-0005 already established for missing tables and missing columns. Deploying and restarting the app (the existing pattern for schema changes) is then sufficient to apply the fix to production; no separate manual migration step.

## User Stories

1. As the operator, I want the cost-forecast and dashboard queries to use indexes instead of full table scans, so that a redeploy+restart alone fixes a real, currently-live performance problem.
2. As a developer, I want index definitions to live in exactly one place (`model.py`), so `CREATE INDEX` statements can't drift from what the code declares, matching the existing table/column convention.
3. As the operator, I want index sync to be additive-only (never drops or alters an existing index), so a bug in the sync logic can't destroy a hand-tuned index or take a lock nobody expected.
4. As the operator, I want index sync to fail loudly and crash startup if it can't verify or extend the schema, consistent with the existing table/column sync behaviour.

## Implementation Decisions

- **Index declarations** (`app/data/mysql/model.py`), via `Index()` objects in each table's `__table_args__` (a tuple alongside the existing `{"schema": "octopus"}` dict, per SQLAlchemy's mixed-args convention):
  - `consumption`: `Index("ix_consumption_energy_period_from", "energy", "period_from")`
  - `agreement`: `Index("ix_agreement_energy_valid_from_valid_to", "energy", "valid_from", "valid_to")`
  - `product_rate`: `Index("ix_product_rate_product_code_region_valid_from_valid_to", "product_code", "region", "valid_from", "valid_to")`
  - `agile_forecast`: `Index("ix_agile_forecast_region_period_from", "region", "period_from")`
  - `job_run`: `Index("ix_job_run_job_name_ran_at", "job_name", "ran_at")`
  - Column order in each composite index follows the leftmost-prefix rule against the actual predicates: equality-filtered columns first (`energy`, `region`, `product_code`, `job_name`), then the range/order column(s) (`period_from`, `valid_from`, `ran_at`). `agreement` only has 7 rows today so this particular index has negligible effect now, but it's free and consistent with every other table getting the same treatment; `product_rate` (36,720 rows) is the one that actually matters most.
- **`MariaDBClient._sync_schema`** (`app/data/mysql/client.py`): after the existing missing-column loop, add a missing-index step — for each table, call `inspector.get_indexes(table.name, schema=schema)` to list live index names, diff against `{index.name for index in table.indexes}`, and for each index present in the model but absent live, call `index.create(bind=connection)` (SQLAlchemy's own `Index.create()`, dialect-aware — same "let the ORM generate DDL" principle the column sync already follows via `CreateColumn`).
- **Never drops or alters an existing index** — if a live index with the same name already exists (regardless of whether its columns match the model), it's left untouched, mirroring the "never alters an existing column" rule for columns. Renaming or changing an index's columns stays a manual, deliberate action outside this tool, consistent with ADR-0005's stated boundary.
- **Failure handling**: no special exception handling around index creation — propagates and crashes startup, identical to the existing column-sync behaviour.
- **`context.md`**: update the existing **Schema Sync** glossary entry to note it now also creates missing indexes, not just tables/columns.

## Testing Decisions

- Test seam: identical to `tests/test_schema_sync.py` — construct `MariaDBClient` against a monkeypatched in-memory SQLite engine, then assert via `sqlalchemy.inspect(engine).get_indexes(table_name)`. No new seam.
- **Missing-index case**: create every table via `SQLBase.metadata.create_all(engine)` but on a stripped declarative base (mirroring the existing `_StrippedConsumption` pattern) that omits the index; construct `MariaDBClient`; assert the index now exists with the expected columns.
- **Already-present case**: full `SQLBase.metadata.create_all(engine)` (which already creates declared indexes for a from-scratch schema); construct `MariaDBClient`; assert construction doesn't raise and the index set is unchanged (mirrors the existing "database with every table already present is left untouched" test).
- **DDL-compiles case**: extend the existing `test_every_declared_table_compiles_as_valid_mariadb_ddl` pattern (or a sibling test) to also compile each declared `Index` against the MariaDB dialect, so a syntax mistake in an index declaration is caught without needing a live MariaDB instance.
- Real MariaDB-specific index-creation behaviour (locking behaviour on a populated `product_rate` table, exact `SHOW INDEX` output) is a manual post-deploy sanity check — re-run `EXPLAIN` against production after deploying and restarting, confirm `type` is no longer `ALL` and `possible_keys`/`key` are populated for the queries that motivated this change.

## Out of Scope

- Any change to the actual query SQL in `grafana/mariadb/queries.md` or `client.py` — those queries are already correct; they just need the underlying indexes to use.
- Widening, renaming, or dropping any existing index or column — stays a manual, deliberate action, same boundary as ADR-0005.
- A versioned migration framework — already rejected in ADR-0005 for this single-target deployment.
- A formal latency SLA/benchmark — success is "no more full table scans on the affected queries, same results," not a specific millisecond target, for a personal home-lab dashboard.

## Further Notes

Discovered while manually building Grafana dashboard panels in the Grafana UI (`feature/grafana-dashboard`) — the user noticed a panel query was slow, which led to `EXPLAIN` confirming the missing-index root cause. Once merged and deployed, the existing Startup Backfill/restart cycle is what actually applies the fix to production — same deployment pattern as every other schema change under ADR-0005.

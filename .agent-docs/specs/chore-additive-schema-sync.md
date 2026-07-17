# Additive-only automatic schema sync

## Problem Statement

`mariadb/init.sql` only executes when MariaDB's data directory is completely empty (Docker's `docker-entrypoint-initdb.d` behaviour). On the Pi's already-populated volume, it silently never re-runs, so every schema change since the app first deployed has required an undocumented manual DDL step nobody remembered to do consistently. This will recur for every planned future feature (tariff comparison, Agile forecast, Grafana dashboard all add their own tables).

## Solution

`MariaDBClient` synchronizes its own schema automatically on every app startup: it creates any table missing from the live database and adds any column missing from an existing table, both diffed against the SQLAlchemy models in `sql_models.py`. The sync is additive-only — it never drops or alters an existing table or column, since that class of change is not safely automatable against the only copy of collected consumption/pricing history. `mariadb/init.sql` shrinks to just creating the `octopus` database; `sql_models.py` becomes the single source of truth for schema, eliminating the drift between it and `init.sql` that cost review time on the prior PR.

## User Stories

1. As the operator, I want the app to create any table my code newly declares, so that deploying a feature with a new table doesn't require me to SSH in and run DDL by hand.
2. As the operator, I want the app to add any column my code newly declares to an existing table, so that additive schema changes (like the recent pricing pipeline) deploy without a manual step.
3. As the operator, I want the sync to never drop or alter existing schema, so that a bug in the sync logic can't destroy collected history — that class of change stays a deliberate, manual, one-off action outside the tool.
4. As the operator, I want the sync to fail loudly and stop the app if it can't verify or extend the schema, so that the app never silently runs against a schema it couldn't confirm.
5. As a developer, I want table and column definitions to live in exactly one place (`sql_models.py`), so that `init.sql` and the models can no longer drift apart.

## Implementation Decisions

- **`SessionBuilder`** (`app/data/mysql/client.py`) currently builds `engine` as a local variable and discards it. It exposes `self.engine` so `MariaDBClient` can reach it for introspection.
- **`MariaDBClient.__init__`** calls a new private sync step as its last action, after `SessionBuilder` is constructed. This keeps the sync self-contained to `MariaDBClient` — `main.py`'s startup orchestration does not need to know about it.
- **Sync mechanism**, in order:
  1. `SQLBase.metadata.create_all(engine, checkfirst=True)` — handles "entirely missing table" for free; this is the same call the `mariadb_client` test fixture already uses.
  2. For every table declared in `SQLBase.metadata.tables` (now guaranteed to exist), use `sqlalchemy.inspect(engine).get_columns(table.name, schema=table.schema)` to list live columns and diff against the columns the model declares. For each column present in the model but absent live, execute `ALTER TABLE {schema}.{table} ADD COLUMN {column_ddl}`.
  3. Column DDL text is generated via SQLAlchemy's own DDL compiler — `sqlalchemy.schema.CreateColumn(column).compile(dialect=engine.dialect)` — rather than a hand-rolled type-to-SQL mapping. This keeps DDL generation dialect-correct (SQLite in tests, MariaDB in prod) and automatically stays in sync as columns are added to `sql_models.py`, avoiding a second place that could drift.
- **Failure handling**: no special catch around the sync. Any exception (from `create_all`, `inspect`, or the `ALTER TABLE` execution) propagates out of `MariaDBClient.__init__` and crashes app startup, consistent with the existing `get_settings` startup-failure precedent in `app/main.py`.
- **`mariadb/init.sql`**: every `CREATE TABLE` / `DROP TABLE` statement is removed, leaving only `CREATE DATABASE IF NOT EXISTS octopus;`.
- **Constraint (non-negotiable)**: the sync never drops a table/column and never alters an existing column's type, nullability, or default. Widening an existing column's constraint (e.g. adding `NOT NULL` to a column with existing data) stays permanently out of scope for this tool.

## Testing Decisions

- Test seam: construct `MariaDBClient` against a monkeypatched in-memory SQLite engine (the same seam `test_mariadb_upsert.py` and the `mariadb_client` fixture in `conftest.py` already use), then assert on the resulting live schema via `sqlalchemy.inspect()`. No new seam is introduced, and no diff function is unit-tested in isolation from construction.
- **Missing-table case**: create every table except one on the engine before constructing `MariaDBClient`; assert the omitted table exists with the correct columns afterward.
- **Missing-column case**: mirror the throwaway-declarative-base pattern already used in `test_mariadb_upsert.py` — build a stripped-down version of one real table (a subset of its columns) as the "before" schema, construct `MariaDBClient` against it, and assert the omitted column now exists.
- **No-op case**: schema already fully current (i.e. the existing `mariadb_client` fixture, which already runs `SQLBase.metadata.create_all` before constructing the client) — construction must not raise. This is implicitly covered by every existing test that already uses that fixture, since the sync now runs on every `MariaDBClient` construction; a dedicated test adds an explicit assertion for clarity.
- Real MariaDB-specific DDL behaviour (schema-qualified `ALTER TABLE` syntax, exact type mapping) is not exercised in this environment (Docker Desktop unavailable in this sandbox) — flagged as a manual post-deploy sanity check, not claimed as verified.

## Out of Scope

- Dropping or altering existing tables/columns (type changes, nullability changes, defaults) — stays a manual, deliberate action.
- A versioned migration framework (Alembic or similar) — rejected in ADR-0005 as unearned operational weight for a single-user, single-target deployment with no rollback requirement.
- Any changes to `tariff_comparison_result`, `agile_forecast`, or `daily_saving` tables from the future roadmap specs — this chore only builds the mechanism those features will rely on.

## Further Notes

Full rationale and the decision record from the prior `/design` session is in [`.agent-docs/adr/0005-additive-only-schema-sync.md`](../adr/0005-additive-only-schema-sync.md). The domain glossary entry is `.agent-docs/context.md` under **Schema Sync** (Data Storage section), already written.

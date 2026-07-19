> Work complete — PR ready to merge.

# Issues: chore-additive-schema-sync

## Missing-table schema sync on startup (#389)

**Blocked by**: None

**User stories**: 1, 4, 5 (partial — table creation only)

### What to build

Expose the SQLAlchemy engine from `SessionBuilder` so `MariaDBClient` can introspect it. Wire `SQLBase.metadata.create_all(engine, checkfirst=True)` into `MariaDBClient.__init__` as its final step, so any table declared in `sql_models.py` but missing from the live database is created automatically on every app startup. No special error handling — let any failure propagate and crash startup, consistent with the existing `get_settings` failure precedent.

### Acceptance criteria

- [x] `SessionBuilder.engine` is accessible to `MariaDBClient`.
- [x] Constructing `MariaDBClient` against a database missing a table that `sql_models.py` declares results in that table existing afterward, with the correct columns.
- [x] Constructing `MariaDBClient` against a database that already has all tables does not raise and is a no-op.
- [x] A test exercises the missing-table case via the same seam `test_mariadb_upsert.py` uses (monkeypatched in-memory SQLite engine), asserting on the resulting schema via `sqlalchemy.inspect()`.

---

## Missing-column schema sync on startup (#390)

**Blocked by**: #389

**User stories**: 2, 4, 5 (remainder — column addition)

### What to build

For every table already present (per #1), diff its live columns (via `sqlalchemy.inspect(engine).get_columns(...)`) against the columns declared on the corresponding model in `sql_models.py`. For any column present in the model but missing live, execute `ALTER TABLE {schema}.{table} ADD COLUMN {column_ddl}`, where `column_ddl` is generated via SQLAlchemy's `CreateColumn(column).compile(dialect=engine.dialect)` rather than a hand-rolled type mapping, so DDL generation stays dialect-correct and never drifts from the model declarations. Never drops or alters an existing column — only adds missing ones.

### Acceptance criteria

- [x] Constructing `MariaDBClient` against a table that exists but is missing a column results in that column existing afterward.
- [x] The sync never issues a `DROP` or column-alteration statement — only `CREATE TABLE` (via #1) and `ADD COLUMN`.
- [x] A test mirrors the throwaway-declarative-base pattern in `test_mariadb_upsert.py`: build a stripped-down version of one real table (fewer columns) as the "before" state, construct `MariaDBClient`, and assert the omitted column now exists.
- [x] A test confirms the full existing schema (all tables, all columns already current) is a no-op — no exception raised.

---

## Collapse mariadb/init.sql to single source of truth (#391)

**Blocked by**: #389, #390

**User stories**: 5

### What to build

Remove every `CREATE TABLE` and `DROP TABLE` statement from `mariadb/init.sql`, leaving only database creation. This is safe only once the sync mechanism from #1 and #2 is in place to take over table/column creation. `sql_models.py` becomes the sole source of truth for schema, eliminating the drift between it and `init.sql`.

### Acceptance criteria

- [x] `mariadb/init.sql` contains only `CREATE DATABASE IF NOT EXISTS octopus;` (no table DDL).
- [x] No test or code path still depends on `init.sql` for table creation.
- [x] `.agent-docs/context.md`'s **MariaDB `octopus` database** and **Schema Sync** entries accurately describe the collapsed responsibility (already updated in this branch's working tree — verify still accurate).

---

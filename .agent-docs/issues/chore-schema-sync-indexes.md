# Issues: chore-schema-sync-indexes

> Work complete — PR ready to merge. Last acceptance criterion is a post-deploy manual check, left unchecked until performed after this ships and the app restarts in production.

## Schema Sync creates missing indexes (#452)

**Blocked by**: None

**User stories**: 1, 2, 3, 4

### What to build

Declare five missing indexes as SQLAlchemy `Index()` objects in `app/data/mysql/model.py`'s `__table_args__` (`consumption`, `agreement`, `product_rate`, `agile_forecast`, `job_run`), then extend `MariaDBClient._sync_schema` in `app/data/mysql/client.py` to diff declared indexes against `inspector.get_indexes()` and create any missing ones via SQLAlchemy's own `Index.create()` — the same additive-only, idempotent pattern already used for missing tables and columns (ADR-0005). Never drops or alters an existing index. Update the "Schema Sync" glossary entry in `.agent-docs/context.md` to mention index sync.

### Acceptance criteria

- [x] All five indexes declared in `model.py` with columns ordered equality-filters-first per the leftmost-prefix rule (`energy`/`region`/`product_code`/`job_name` before the range/order column).
- [x] `MariaDBClient._sync_schema` creates any index declared in the model but missing from the live database.
- [x] An index that already exists live (by name) is left untouched — never dropped, altered, or recreated.
- [x] Test: a stripped schema missing one of the declared indexes gets that index created on `MariaDBClient` construction, verified via `inspect(engine).get_indexes(...)`.
- [x] Test: a schema with every index already present is left unchanged and construction doesn't raise.
- [x] Test: every declared `Index` compiles as valid MariaDB DDL (dialect-compile check, no live MariaDB needed).
- [x] `.agent-docs/context.md`'s Schema Sync entry updated to mention index creation.
- [ ] Post-merge manual check (not a test): after deploying and restarting the app, `EXPLAIN` against production shows indexed access (not `type=ALL`) for the `consumption`⋈`agreement`⋈`product_rate` join.

---

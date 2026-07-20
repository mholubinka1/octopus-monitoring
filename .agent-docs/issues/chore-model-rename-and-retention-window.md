# Issues: chore-model-rename-and-retention-window

> Work complete — PR ready to merge.

## Rename sql_models.py to model.py, remove dead `_deprecated` code (#398)

**Blocked by**: None

**User stories**: 1

### What to build

Rename `app/data/mysql/sql_models.py` → `app/data/mysql/model.py` (pure
rename, no content changes) and update every importer (`app/data/mysql/client.py`
plus all test files currently importing `from data.mysql import sql_models`)
to `from data.mysql import model`. Delete `app/_deprecated/` entirely
(`calc.py`, `extract.py`, `influx.py`) — legacy InfluxDB code already
documented in `.agent-docs/context.md` as unreferenced by `main.py`. Also
delete `app/data/mysql/utils.py`, already empty and unreferenced.

### Acceptance criteria

- [x] `app/data/mysql/sql_models.py` no longer exists; `app/data/mysql/model.py`
      exists with identical content.
- [x] `app/_deprecated/` no longer exists.
- [x] `app/data/mysql/utils.py` no longer exists.
- [x] No remaining reference to `sql_models` anywhere in `app/` or `tests/`.
- [x] Full test suite passes unchanged (79 tests, pre-existing — this is a
      pure rename/deletion, no new test scenarios needed).

---

## Rename historical_limit_days to retention_days, widen to 400 days (#399)

**Blocked by**: None

**User stories**: 2, 3

### What to build

Rename `config.yml`'s `data_refresh.historical_limit_days` →
`retention_days` (and `RefreshSettings.historical_limit` → `retention` in
`app/common/config.py`), updating `app/main.py`'s reference in `startup()`,
`config.yml.template` (value becomes `400`), and README's Configuration
section. Revise `.agent-docs/adr/0003-90-day-data-retention.md` from 90 to
400 days, noting the pruning job itself is still unimplemented (separate
future work — this chore only changes the number the startup backfill
already uses). Fix `.agent-docs/context.md`'s "Startup Backfill" glossary
entry, which incorrectly calls the backfill "one-time" — confirmed via
`app/data/consumption.py` that `ConsumptionRetriever`'s watermark is
in-memory only, so it actually re-runs on every process restart, from
`retention_days` ago each time.

### Acceptance criteria

- [x] `config.yml.template` has `retention_days: 400` (not
      `historical_limit_days: 45`).
- [x] `RefreshSettings.retention` (aliased from `retention_days`) replaces
      `RefreshSettings.historical_limit`; `main.py` references the new name.
- [x] `tests/test_config_settings.py` and `tests/test_refresh_scheduling.py`
      updated to the renamed field; full suite passes.
- [x] ADR-0003 states 400 days and explicitly notes the pruning job is not
      yet built.
- [x] `.agent-docs/context.md`'s "Startup Backfill" entry accurately
      describes every-restart re-run behavior (not "one-time") and
      references `retention_days`/400.
- [x] README's Configuration section reflects the renamed field.

---

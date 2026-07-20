# Rename sql_models to model, remove dead code, and widen the retention/backfill window to 400 days

## Problem Statement

Two unrelated pieces of housekeeping surfaced together this session:

1. `app/data/mysql/sql_models.py` carries a redundant "sql_" prefix (it lives in
   the `mysql` package already), and `app/_deprecated/` still holds legacy
   InfluxDB code (`calc.py`, `extract.py`, `influx.py`) that
   `.agent-docs/context.md` already documents as "no longer wired into
   `main.py`" — dead weight with no reason to still exist in the tree.
2. ADR-0003 documents a 90-day retention policy, but no pruning job actually
   exists yet in code — data already grows unbounded today. Separately, the
   user wants deeper historical data (a full year+) available for upcoming
   dashboard work, and wants the app's startup historical backfill to use
   the same number as the (future) retention window, rather than two
   independently configured values that could drift apart from each other —
   exactly the kind of duplicated-concept problem this repo has already
   fixed once this session (the `.env`/`config.yml` MariaDB credential
   consolidation).

## Solution

- Rename `sql_models.py` → `model.py`; delete `app/_deprecated/` entirely.
- Revise ADR-0003 to state 400 days instead of 90, and record explicitly that
  the pruning job itself is still unimplemented (tracked as separate future
  work — not part of this chore).
- Rename `config.yml`'s `data_refresh.historical_limit_days` →
  `retention_days` (and `RefreshSettings.historical_limit` → `retention`),
  set its value to `400`, and fix `.agent-docs/context.md`'s "Startup
  Backfill" glossary entry, which currently (and incorrectly) calls this
  "one-time" — there is no persisted watermark, so it actually re-runs on
  every process restart.

## User Stories

1. As a developer navigating this codebase, I want the SQL model module
   named for what it is (`model.py`, matching sibling modules like
   `data/octopus/model.py`) rather than carrying a redundant `sql_` prefix,
   and want dead legacy code gone rather than lingering as something a
   future reader might wonder is still relevant.
2. As the operator of this app, I want the startup historical backfill and
   the (future) retention window to be governed by one config value, so
   that a year-plus of consumption history is available for dashboard work
   without having to keep two separately-configured numbers in sync by hand.
3. As a future reader of `.agent-docs/context.md`, I want the "Startup
   Backfill" glossary entry to accurately describe that it re-runs on every
   restart (not just once), so I don't build a wrong mental model of how
   often this hits the Octopus API.

## Implementation Decisions

- **`app/data/mysql/sql_models.py` → `app/data/mysql/model.py`**: pure
  rename, no content changes. Every importer (`app/data/mysql/client.py` and
  all test files importing `from data.mysql import sql_models`) updated to
  `from data.mysql import model`.
- **`app/_deprecated/` deleted entirely** (`calc.py`, `extract.py`,
  `influx.py`) — already unreferenced by `main.py` per
  `.agent-docs/context.md`'s existing "InfluxDB (legacy)" glossary entry.
- **`app/common/config.py`**: `RefreshSettings.historical_limit: int =
  Field(alias="historical_limit_days")` becomes `RefreshSettings.retention:
  int = Field(alias="retention_days")`.
- **`app/main.py`**: `refresh_config.historical_limit` reference in
  `startup()` becomes `refresh_config.retention`.
- **`config.yml.template`**: `historical_limit_days: 45` becomes
  `retention_days: 400`.
- **README.md**: the Configuration section's field list updated
  (`historical_limit_days` → `retention_days`, description updated to
  reflect it now doubles as the intended retention window).
- **`.agent-docs/adr/0003-90-day-data-retention.md`**: revise "90 days" to
  "400 days" throughout, and add a line noting the pruning job described
  here is not yet implemented — this chore only widens the number the app
  already uses for its startup backfill; the actual daily pruning job is
  separate, future work.
- **`.agent-docs/context.md`**: fix the "Startup Backfill" entry's "one-time"
  claim — `ConsumptionRetriever`'s `_latest_retrieved_date` watermark is
  in-memory only (confirmed by reading `app/data/consumption.py`), so
  `main.py`'s `startup()` re-runs this backfill, from `retention_days` ago,
  on every process restart, not just the first ever run. Also update the
  entry to reference `retention_days` (renamed) instead of
  `historical_limit_days`, with 400 as the new default called out.
- No change to `ConsumptionRetriever`/`main.py`'s actual backfill *mechanism*
  — it already re-fetches and upserts on every restart; this chore only
  changes *how far back* that already-existing behavior reaches.
- **Explicit, real consequence** (documented here since it's exactly the
  kind of thing a future reader would wonder about): every future restart
  now re-fetches and re-upserts roughly 400 days × 48 half-hourly readings ×
  2 meters (≈38,400 records) from the Octopus API, versus roughly 45 days
  (≈4,300 records) today. This was a deliberate, explicit trade-off the user
  chose over a one-time-only deep backfill, specifically so the startup
  lookback always matches the retention window going forward.

## Testing Decisions

- **`tests/test_config_settings.py`**: update `VALID_CONFIG`'s
  `historical_limit_days` key to `retention_days`, and the assertion
  `settings.refresh_settings.historical_limit == 45` to
  `settings.refresh_settings.retention == 45` (test data value itself
  doesn't need to become 400 — it's testing the parsing mechanism, not the
  production default).
- **`tests/test_refresh_scheduling.py`**: `RefreshSettings(refresh_interval=4,
  historical_limit=45)` becomes `RefreshSettings(refresh_interval=4,
  retention=45)`.
- All other test files' `sql_models` → `model` import rename is a pure
  mechanical find-and-replace with no behavioral test changes needed — the
  full suite (79 tests, pre-existing, before any new work in this chore)
  already passes unchanged against the renamed module, confirming the
  rename introduced no regressions.
- No new test scenarios are needed beyond the renamed assertions above —
  this chore is a rename plus a config value/name change, not new logic.

## Out of Scope

- Building the actual daily pruning job (ADR-0003's described behavior) —
  explicitly deferred by the user to a separate, future round of work.
- Any change to `ConsumptionRetriever`/`main.py`'s backfill *mechanism*
  (e.g. persisting a watermark to avoid re-fetching on every restart) — the
  user was explicit that the existing every-restart re-fetch, now reaching
  further back, is the intended (if more expensive) behavior for now.
- Any change to `mariadb/init.sql`, `docker-compose.yml`, or the
  `pi-desktop` deployment — unrelated to this chore.

## Further Notes

This chore was scoped mid-session, layered onto a rename/dead-code-removal
the user had already started making directly in the working tree (verified
against the full test suite before this spec was written). The retention/
backfill unification was added to the same branch at the user's explicit
request, reusing the same "don't let one concept hide behind two config
values" principle already applied earlier this session to the
`.env`/`config.yml` MariaDB credentials.

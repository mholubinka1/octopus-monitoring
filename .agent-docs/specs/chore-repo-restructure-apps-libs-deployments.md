# Repo restructure: apps/libs/data/deployments layout

## Problem Statement

This repo now hosts two data-gathering containers — `octopus-app` (as `app/`) and `hive-app` (as `hive_app/`) — but its layout still assumes a single app: a generic `app/common/` and `app/data/mysql/` that a second container (`hive-app`) has to duplicate wholesale rather than share, a root `pyproject.toml`/`uv.lock` that installs every dependency either app needs into both Docker images, a single `docker-compose.yml` and two ad hoc root Dockerfiles with no per-app grouping, and CI checks (mypy/isort/black/ruff/pylint) that only run against `app tests`, silently leaving `hive_app` unchecked by five of the seven quality gates. Anyone reading the repo today can't tell, from its shape alone, that it's meant to host more than one independently deployable service.

## Solution

Restructure the repo into four top-level folders that each mean one thing: `apps/` (deployable containers only — `octopus-app`, `hive-app`), `libs/` (`common`, the one genuinely shared infrastructure package — no container of its own), `data/` (`grafana/`, `mariadb/` — non-code assets for the shared datastore and dashboard), and `deployments/` (every Dockerfile and compose file). The root becomes a uv workspace so each app's image only installs what that app actually needs, while `libs/common` (logging setup, MariaDB engine/session plumbing, the Schema Sync mechanism, and the shared `job_run` table) is written once and depended on by both apps instead of hand-copied. This is a structural reshuffle only — no behavior changes, no data migration, no repo/database/Docker-Hub-image rename (those are separate, later, explicitly-confirmed steps).

## User Stories

1. As a maintainer, I want each deployable container under `apps/` with its own package, tests, and `pyproject.toml`, so that I can tell at a glance what's deployable and what isn't, and add a third app later without disturbing the other two.
2. As a maintainer, I want the genuinely shared infrastructure code (logging, MariaDB session/engine plumbing, Schema Sync, `job_run`) written once in `libs/common`, so that a bug fix or behavior change to that plumbing doesn't require me to remember to apply it twice.
3. As a maintainer, I want each app's Docker image to install only that app's own dependencies (not the other app's), so that `octopus-app`'s image doesn't carry `pyhive-integration` and `hive-app`'s doesn't carry Octopus-specific packages.
4. As a maintainer, I want CI to lint, type-check, and test every package (`octopus-app`, `hive-app`, `common`) — not just `octopus-app` as today — so that `hive-app` gets the same quality gate `octopus-app` always has.
5. As a maintainer, I want `deployments/` to hold every Dockerfile and compose file, with a single top-level compose file that composes the three per-app/service compose files via `include:`, so that the Pi's actual deploy command stays one file while each service's compose definition is independently readable.
6. As a maintainer, I want this restructure to be a pure move-and-rename with no functional change, so that the existing test suite is the proof the restructure didn't break anything — not a manual QA pass.

## Implementation Decisions

### Layout

```text
apps/
  octopus-app/
    octopus_app/            (renamed from app/ — package import name becomes octopus_app, matching hive_app's convention)
      common/                (retry.py fixed-delay retry, exceptions.py, config.py — app-specific, NOT moved to libs/common)
      data/
        octopus/             (Octopus API client, unchanged)
        model.py, consumption.py, consumption_summary.py, cost_forecast.py,
        local_day.py, pricing.py, pruning.py, agile_forecast.py
        mysql/
          model.py            (octopus-app's own SQLAlchemy models — consumption, agreement, product, product_rate,
                                daily_consumption_summary, agile_forecast, cost_forecast; job_run REMOVED, now libs/common's)
          client.py            (octopus-app's own MariaDBClient subclass/composition for domain CRUD;
                                 engine/session/schema-sync/job_run delegated to libs/common)
      main.py
    tests/                    (relocated from root tests/, minus tests/hive_app/)
    pyproject.toml            (octopus-app's own deps: requests, pyyaml, sqlalchemy, pymysql, schedule, pydantic,
                                tzdata; NOT pyhive-integration; workspace dependency on common)
  hive-app/
    hive_app/                 (relocated from root hive_app/, unchanged internal structure)
      common/                 (config.py, decorator.py [exponential backoff retry], exceptions.py — hive-app-specific)
      data/
        auth.py, heating.py, hive_client.py, model.py
        mysql/
          model.py             (hive-app's own models — heating_status; job_run REMOVED, now libs/common's)
          client.py             (hive-app's own domain CRUD; engine/session/schema-sync/job_run delegated to libs/common)
      main.py
    tests/                    (relocated from root tests/hive_app/)
    pyproject.toml            (hive-app's own deps: pyhive-integration, pydantic, pyyaml, sqlalchemy, pymysql,
                                schedule, tzdata; workspace dependency on common)
libs/
  common/
    common/
      logging.py               (APP_LOGGER_NAME becomes a constructor/module-level parameter each app supplies its
                                 own logger name to, not a hardcoded module constant — see below)
      mariadb/
        client.py               (engine creation, session_read_scope/session_write_scope context managers, the
                                 additive-only schema-sync diff-and-create logic incl. the CREATE TABLE race retry,
                                 sync_missing_indexes; parameterized by a SQLAlchemy declarative base and an
                                 engine/connection string, not hardcoded to either app's model module)
        model.py                (job_run only)
    tests/
    pyproject.toml              (deps: sqlalchemy, pymysql; no app-specific deps)
data/
  grafana/
    dashboard.json              (relocated from grafana/, unchanged)
  mariadb/
    init.sql                    (relocated from mariadb/, unchanged — still just CREATE DATABASE IF NOT EXISTS octopus;
                                  database rename to home_monitoring is explicitly out of scope, see below)
deployments/
  docker-compose.yml            (new — no services of its own; `include:` of the three files below)
  octopus-app/
    Dockerfile                  (relocated from root Dockerfile; COPY paths updated to apps/octopus-app/...,
                                  build context stays repo root)
    docker-compose.yml           (the energy-monitor service, extracted verbatim from today's root docker-compose.yml)
  hive-app/
    Dockerfile                  (relocated from root Dockerfile.hive-app; COPY paths updated to apps/hive-app/...)
    docker-compose.yml           (the hive-app service, extracted verbatim)
  mariadb/
    docker-compose.yml           (the mariadb service, extracted verbatim; still points at data/mariadb/init.sql
                                  and today's octopus database/volume paths — no data migration in this spec)
pyproject.toml                  (workspace root — [tool.uv.workspace] members = ["apps/octopus-app", "apps/hive-app",
                                  "libs/common"]; no [project.dependencies] of its own; owns [tool.pytest.ini_options],
                                  [tool.mypy]/setup.cfg equivalent, [tool.ruff], [tool.pylint], [tool.coverage.run])
uv.lock                          (one lockfile for the whole workspace)
setup.cfg                        (mypy config — source-roots/exclude paths updated to the new package locations)
```

### `libs/common`'s exact surface (per ADR-0020)

- Logging config (`config` dict, `APP_LOGGER_NAME`) — the dict-shape stays identical; each app passes its own logger name in rather than `common` hardcoding one, since `octopus-app` and `hive-app` use different logger names today (`octopus-monitor` vs `hive-monitor`).
- `MariaDBClient` base: engine creation, `session_read_scope`/`session_write_scope`, the additive-only schema-sync loop (`_sync_missing_indexes`, the `CREATE TABLE` race-retry logic and its `_is_table_already_exists_error` helper) — templated on a SQLAlchemy declarative base and connection settings the calling app supplies, not on either app's own model module.
- `job_run` SQLAlchemy model and its CRUD (`has_successful_job_run`, `latest_job_run_is_successful`, the write path used by each app's job-runner wrapper in `main.py`).
- `MariaDBSettings` and `MariaDBError` — pulled into `libs/common` alongside the client during implementation (issue #527): both were byte-identical duplicates across `app/common/config.py`/`hive_app/common/config.py` and `app/common/exceptions.py`/`hive_app/common/exceptions.py` respectively, and `MariaDBClientBase`'s own constructor and write-path error wrapping need them directly — they're infrastructure types for the shared client, not app-specific config/exception surface.

Everything else — retry/backoff strategy (genuinely different: `octopus-app`'s fixed-delay `retry()` vs `hive-app`'s `retry_with_exponential_backoff()`), the `ApplicationSettings`/`HiveApplicationSettings` config schemas themselves (everything except `MariaDBSettings`), every other exception type, and all domain-specific models/CRUD (consumption, pricing, cost forecast, heating status) — stays in its own app's package, unchanged in behavior.

### Packaging (per ADR-0021)

- Root `pyproject.toml` becomes the uv workspace root: `[tool.uv.workspace] members = [...]`, no `[project.dependencies]`.
- `apps/octopus-app/pyproject.toml`, `apps/hive-app/pyproject.toml`, `libs/common/pyproject.toml` each declare only their own runtime dependencies, split out of today's single dependency list by which app currently imports them. Both apps add a workspace path-dependency on `common`.
- One `uv.lock` at the root. `uv sync --package octopus-app` / `uv sync --package hive-app` installs only that member's dependency closure — this is what each Dockerfile's `RUN uv sync --frozen --no-dev --no-install-project` step targets, via `--package <name>`.
- Dev dependency group (`isort`, `black`, `mypy`, `ruff`, `pre-commit`, `pytest`, etc.) stays at the workspace root — these are tooling, not runtime deps, and apply uniformly across all three packages.

### Tests (per ADR-0021 and the confirmed test seam)

- Tests move inside each package: `apps/octopus-app/tests/`, `apps/hive-app/tests/` (today's `tests/hive_app/`), `libs/common/tests/` (new — covers the extracted engine/session/schema-sync/`job_run` logic, since that logic currently has no dedicated tests of its own, only indirect coverage via each app's `mysql/client.py` tests).
- One combined pytest run, not per-package: the workspace-root `pyproject.toml` owns `[tool.pytest.ini_options]` — `testpaths = ["apps/octopus-app/tests", "apps/hive-app/tests", "libs/common/tests"]`, `pythonpath = ["apps/octopus-app", "apps/hive-app", "libs/common"]`. A single `pytest` invocation from the repo root runs everything, same as today's single test run.
- `[tool.coverage.run] source = ["apps/octopus-app/octopus_app", "apps/hive-app/hive_app", "libs/common/common"]`.

### CI (per the design session's #495 resolution)

- `.github/actions/code-quality-checks/action.yml`'s mypy/isort/black/ruff/pylint steps currently target `app tests` only — this restructure extends every one of those steps to cover all three packages (`apps/octopus-app/octopus_app apps/hive-app/hive_app libs/common/common` plus their respective `tests/`), closing the existing gap where `hive_app` was never linted or type-checked. This is the "per-package steps" shape agreed in the design session, expressed as one workflow whose existing steps widen their target paths — not a new matrix job, since these are fast static-analysis steps, not builds.
- `setup.cfg`'s `[mypy]` section (`source-roots`, `exclude`) updates to the new paths.
- `.github/workflows/ci-arm64.yml`: the coverage/test step's `--cov=app` becomes `--cov=apps/octopus-app/octopus_app --cov=apps/hive-app/hive_app --cov=libs/common/common` (or simply relies on the root `[tool.coverage.run] source` list from pyproject.toml, dropping the explicit `--cov=` flags). The two `docker buildx build` steps' `-f` flags update to `deployments/octopus-app/Dockerfile` and `deployments/hive-app/Dockerfile`; build context (`.`, the trailing arg) stays the repo root so COPY paths inside each Dockerfile can still reach `apps/<app>/` and `libs/common/`. Coverage-baseline auto-commit behavior (the "[skip ci]" push straight to the branch) is unchanged.
- Root `docker-compose.yml` is deleted; `deployments/docker-compose.yml` (with its `include:` of the three per-service files) takes over as the file referenced by any docs/scripts.

## Testing Decisions

- **No new test *behavior* is required or expected.** This spec's entire correctness bar is: the existing test suite (once its imports are mechanically updated from `app.`/`hive_app.` to `octopus_app.`/`hive_app.`/`common.` as each piece of code moves) passes unchanged, proving the move didn't alter behavior.
- **New tests are needed for `libs/common`** specifically because its engine/session/schema-sync/`job_run` logic currently has no dedicated test file of its own (it's only exercised indirectly through each app's `mysql/client.py` tests, e.g. `tests/test_mariadb_upsert.py`, `tests/test_schema_sync.py`, `tests/test_schema_sync_concurrency.py`, `tests/test_job_run_recording.py`). Move/adapt those specific test cases into `libs/common/tests/`, parameterized against a throwaway declarative base rather than either app's real models, and leave each app's own `mysql/client.py` tests covering only that app's domain CRUD.
- **Test seam**: SQLite-backed `MariaDBClient` tests (the existing pattern — see `tests/conftest.py`) stay the seam of choice; no new integration/e2e seam is introduced by this spec.
- Prior art: `tests/test_schema_sync.py` and `tests/test_schema_sync_concurrency.py` are the closest existing tests to what `libs/common/tests/` needs to end up covering.

## Out of Scope

- GitHub repo rename (`octopus-monitoring` → `home-monitoring`) — Wayfinder #496, deferred at the time this spec was written. **Since resolved**: #496 shipped via [PR #536](https://github.com/mholubinka1/home-monitoring/pull/536); the GitHub repo is now `mholubinka1/home-monitoring`. Left unedited above as historical record of this spec's own scope.
- Docker Hub image rename (`mholubinka1/octopus-monitoring` → `mholubinka1/octopus-app`) — part of #495, deferred; this spec's CI changes keep publishing to the existing image names.
- MariaDB database rename (`octopus` → `home_monitoring`) and any live-data migration — ADR-0022's rename is explicitly deferred; `data/mariadb/init.sql` still creates a database named `octopus`.
- The live Pi deployment cutover itself (stopping/starting containers, updating the Pi's `docker-compose.yml`) — this spec only produces the new `deployments/` files in the repo; rolling them out to the Pi is a separate, later, explicitly-confirmed step.
- Any functional/behavioral change to either app — this is a pure structural move.
- The hive-app epic issues (#508–#514) — explicitly deferred until this restructure lands, per the handoff doc that prompted this session.

## Further Notes

- This spec resolves the code-relevant portions of Wayfinder tickets #491, #497, #492, and #495 (already recorded as ADR-0020, ADR-0021, ADR-0022, and comments on each ticket from the preceding `/design` session). #496 (repo rename) and the deployment/data-migration halves of #492/#495 remain open, to be picked up once this lands and is verified stable.
- `CLAUDE.md` and `.agent-docs/agent.md` don't reference specific file paths that this restructure would break, but README.md likely references the root `Dockerfile`/`docker-compose.yml` paths and should be checked during implementation.
- `.pre-commit-config.yaml` may reference `app`/`hive_app` paths for hook scoping (e.g. per-file-type excludes) and should be checked during implementation.

# Issues: chore-repo-restructure-apps-libs-deployments

## Extract libs/common (engine/session/schema-sync/job_run)

**GitHub issue**: #527

**Blocked by**: None

**User stories**: 2, 4, 6

### What to build

Create the `libs/common` package: a `MariaDBClient` base providing engine creation, `session_read_scope`/`session_write_scope`, and the additive-only Schema Sync mechanism (the diff-and-create loop, missing-index sync, and the `CREATE TABLE` race retry), parameterized by a caller-supplied declarative base and connection settings rather than hardcoded to either app's model module. Move the `job_run` SQLAlchemy model and its CRUD (`has_successful_job_run`, `latest_job_run_is_successful`, the write path used by each job-runner wrapper) into this package, removing the duplicate `job_run` definitions from `app/data/mysql/model.py` and `hive_app/data/mysql/model.py`. Update both apps' `MariaDBClient`s to build on the shared base instead of their own copy of this plumbing, and to call the shared `job_run` CRUD instead of their own. Logging config also moves here, parameterized by the logger name each app already supplies (`octopus-monitor` / `hive-monitor`) rather than a hardcoded constant.

Apps stay at their current `app/` and `hive_app/` locations in this slice — only their internal imports change to pull engine/session/schema-sync/`job_run`/logging from `libs.common` instead of their own duplicated copies.

### Acceptance criteria

- [ ] `libs/common/common/mariadb/client.py` provides engine/session/schema-sync plumbing with no reference to either app's own models
- [ ] `libs/common/common/mariadb/model.py` holds the single `job_run` model; both apps' own `model.py` no longer define it
- [ ] `libs/common/common/logging.py` provides the logging config dict, parameterized by logger name
- [ ] `libs/common/tests/` covers schema-sync (including the concurrent-create race) and `job_run` CRUD — adapted from `tests/test_schema_sync.py`, `tests/test_schema_sync_concurrency.py`, `tests/test_job_run_recording.py`
- [ ] Both `app/` and `hive_app/` build on the shared base for engine/session/schema-sync/`job_run`/logging; their own domain models and CRUD are unchanged in behavior
- [ ] Full existing test suite (both apps) passes unchanged

---

## Move octopus-app to apps/octopus-app/, rename package app → octopus_app

**GitHub issue**: #528

**Blocked by**: #527

**User stories**: 1, 3, 6

### What to build

Relocate `app/` to `apps/octopus-app/octopus_app/`, renaming the importable package from `app` to `octopus_app` throughout (every `from app...`/`import app...` across source and tests). Relocate `tests/` (excluding `tests/hive_app/`) to `apps/octopus-app/tests/`. Give `apps/octopus-app/` its own `pyproject.toml` declaring only octopus-app's runtime dependencies (`requests`, `pyyaml`, `sqlalchemy`, `pymysql`, `schedule`, `pydantic`, `tzdata` — not `pyhive-integration`), plus a workspace path-dependency on `common`.

### Acceptance criteria

- [ ] `apps/octopus-app/octopus_app/` contains everything that was `app/`, importable as `octopus_app`
- [ ] `apps/octopus-app/tests/` contains octopus-app's tests, all imports updated
- [ ] `apps/octopus-app/pyproject.toml` declares only octopus-app's own dependencies plus a workspace dependency on `common`
- [ ] `uv sync --package octopus-app` installs a dependency closure with no `pyhive-integration`
- [ ] octopus-app's test suite passes unchanged from its new location

---

## Move hive-app to apps/hive-app/

**GitHub issue**: #529

**Blocked by**: #527

**User stories**: 1, 3, 6

### What to build

Relocate `hive_app/` to `apps/hive-app/hive_app/` (package import name `hive_app` is unchanged — already matches the target convention). Relocate `tests/hive_app/` to `apps/hive-app/tests/`. Give `apps/hive-app/` its own `pyproject.toml` declaring only hive-app's runtime dependencies (`pyhive-integration`, `pydantic`, `pyyaml`, `sqlalchemy`, `pymysql`, `schedule`, `tzdata`), plus a workspace path-dependency on `common`.

### Acceptance criteria

- [ ] `apps/hive-app/hive_app/` contains everything that was `hive_app/`, importable as `hive_app`
- [ ] `apps/hive-app/tests/` contains hive-app's tests, all imports updated
- [ ] `apps/hive-app/pyproject.toml` declares only hive-app's own dependencies plus a workspace dependency on `common`
- [ ] hive-app's test suite passes unchanged from its new location

---

## Move data/ and deployments/, add workspace root config

**GitHub issue**: #530

**Blocked by**: #528, #529

**User stories**: 5, 6

### What to build

Relocate `grafana/` → `data/grafana/` and `mariadb/` → `data/mariadb/` (contents unchanged). Relocate the root `Dockerfile` → `deployments/octopus-app/Dockerfile` and `Dockerfile.hive-app` → `deployments/hive-app/Dockerfile`, updating each Dockerfile's `COPY` paths to reach `apps/<app>/` and `libs/common/` from a repo-root build context. Split today's single root `docker-compose.yml` into `deployments/octopus-app/docker-compose.yml`, `deployments/hive-app/docker-compose.yml`, and `deployments/mariadb/docker-compose.yml` (each service extracted verbatim, pointing at `data/mariadb/init.sql` where relevant), and add `deployments/docker-compose.yml` with no services of its own, using Compose `include:` to pull in the three per-service files. Delete the root `docker-compose.yml`, `Dockerfile`, and `Dockerfile.hive-app`. Convert the root `pyproject.toml` into the uv workspace root (`[tool.uv.workspace] members = [...]`, no `[project.dependencies]`), owning `[tool.pytest.ini_options]` (testpaths/pythonpath covering all three packages' test dirs), `[tool.coverage.run]`, `[tool.ruff]`, and `[tool.pylint]`. Update `setup.cfg`'s `[mypy]` section for the new paths.

### Acceptance criteria

- [ ] `data/grafana/dashboard.json` and `data/mariadb/init.sql` exist; old `grafana/`/`mariadb/` removed
- [ ] `deployments/octopus-app/Dockerfile` and `deployments/hive-app/Dockerfile` build successfully from a repo-root context
- [ ] `deployments/{octopus-app,hive-app,mariadb}/docker-compose.yml` each validate independently (`docker compose -f <file> config`)
- [ ] `deployments/docker-compose.yml` validates and resolves to the same three services as today's root file (`docker compose -f deployments/docker-compose.yml config`)
- [ ] Root `pyproject.toml` is a valid uv workspace root; `uv sync` from the repo root succeeds
- [ ] `pytest` from the repo root (no path args) discovers and runs all three packages' tests via `testpaths`
- [ ] No `Dockerfile`, `Dockerfile.hive-app`, or `docker-compose.yml` remain at the repo root

---

## Update CI: lint/type-check/test all three packages, fix Docker build paths

**GitHub issue**: #531

**Blocked by**: #530

**User stories**: 4, 6

### What to build

Extend `.github/actions/code-quality-checks/action.yml`'s mypy, isort, black, ruff, and pylint steps to target all three packages (`apps/octopus-app/octopus_app`, `apps/hive-app/hive_app`, `libs/common/common`, plus their respective `tests/`) instead of just `app tests` — this closes the existing gap where `hive_app` was never linted or type-checked. Update `.github/workflows/ci-arm64.yml`'s coverage step to source coverage from all three packages (via the root `[tool.coverage.run]` config from the previous slice, or explicit `--cov=` flags per package) and update both `docker buildx build -f` flags to `deployments/octopus-app/Dockerfile` and `deployments/hive-app/Dockerfile`. Verify `bandit`'s `-r` target and any other path-scoped step in the composite action.

### Acceptance criteria

- [ ] mypy, isort, black, ruff, pylint all run against all three packages (octopus-app, hive-app, common) and their tests
- [ ] `hive-app` now fails these checks the same way `octopus-app` always has, if it has violations (i.e. it's actually covered, not silently skipped)
- [ ] Coverage step in `ci-arm64.yml` measures all three packages
- [ ] Both Docker build steps in `ci-arm64.yml` reference the new Dockerfile paths and still build successfully
- [ ] Coverage-baseline auto-commit behavior (`[skip ci]` push) is unchanged
- [ ] Full CI pipeline (code-quality-checks + ci-arm64) passes green on this branch

---

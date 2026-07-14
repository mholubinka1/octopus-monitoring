# Issues: chore-operational-hygiene

## Test infrastructure + CI gate

**GitHub issue**: [#366](https://github.com/mholubinka1/octopus-monitoring/issues/366)

**Blocked by**: None

**User stories**: 4

### What to build

Add `pytest` and `responses` as dev dependencies, create a `tests/` directory, and add a `pytest` step to `.github/workflows/ci-arm64.yml` that runs before the Docker build/push step and fails the job if tests fail. Include one seam-establishing test that exercises the SQLite in-memory session + `responses` mocking pattern, so the CI gate has something real to check and later slices have a pattern to copy.

### Acceptance criteria

- [ ] `pytest` and `responses` added to `pyproject.toml`'s dev dependency group
- [ ] `tests/` directory created with at least one passing test establishing the SQLite in-memory + `responses` seam pattern
- [ ] `.github/workflows/ci-arm64.yml` runs `pytest` before the "Docker Build and Push" step
- [ ] CI fails fast (build/push does not run) if `pytest` fails

---

## Fix hardcoded refresh interval

**GitHub issue**: [#367](https://github.com/mholubinka1/octopus-monitoring/issues/367)

**Blocked by**: [#366](https://github.com/mholubinka1/octopus-monitoring/issues/366)

**User stories**: 1

### What to build

Extract job registration in `app/main.py` into a testable function, and replace the hardcoded `@repeat(every(60).seconds, ...)` with a job driven by `refresh_config.refresh_interval`. Register jobs individually (not as one hardcoded repeat) so later specs can add their own jobs on independent cadences using the same `schedule` library.

### Acceptance criteria

- [ ] Job registration extracted into a testable function in `app/main.py`
- [ ] Hardcoded 60-second repeat replaced with a job driven by `refresh_config.refresh_interval`
- [ ] Unit test asserts the configured interval (not a hardcoded value) is what gets registered
- [ ] Manual verification: changing `refresh_interval_hours` in config changes the polling cadence

---

## `job_run` table + outcome recording

**GitHub issue**: [#368](https://github.com/mholubinka1/octopus-monitoring/issues/368)

**Blocked by**: [#366](https://github.com/mholubinka1/octopus-monitoring/issues/366)

**User stories**: 5

### What to build

Add a `job_run` table (`id, job_name, status, ran_at, error_message`) to `mariadb/init.sql` and `app/data/mysql/sql_models.py`. Add `MariaDBClient.record_job_run(job_name, status, error=None)` following the existing `upsert`/`session_write_scope` pattern used by `write_consumption`. Wrap the consumption refresh job so every run records its outcome — this is the mechanism later specs (tariff comparison, forecast fetch) reuse for their own jobs, and what the future dashboard health panel reads from.

### Acceptance criteria

- [ ] `job_run` table added to `mariadb/init.sql` and `app/data/mysql/sql_models.py`
- [ ] `MariaDBClient.record_job_run(job_name, status, error=None)` implemented following the existing upsert pattern
- [ ] Consumption refresh job wrapped so both success and failure are recorded via `record_job_run`
- [ ] Unit tests against a SQLite in-memory session cover both the success and failure paths

---

## Restore docker-compose app service

**GitHub issue**: [#369](https://github.com/mholubinka1/octopus-monitoring/issues/369)

**Blocked by**: None

**User stories**: 2

### What to build

Uncomment/restore the `energy-monitor` service block in `docker-compose.yml` so `docker compose up` starts the full stack. Host-specific volume paths are left as-is — this is a personal deployment and paths are user-editable.

### Acceptance criteria

- [ ] `energy-monitor` service uncommented/restored in `docker-compose.yml`
- [ ] `docker compose up` starts both the `mariadb` and `energy-monitor` containers
- [ ] `energy-monitor` successfully connects to `mariadb` with no manual steps beyond `docker compose up`

---

## Rewrite README

**GitHub issue**: [#370](https://github.com/mholubinka1/octopus-monitoring/issues/370)

**Blocked by**: None

**User stories**: 3

### What to build

Rewrite `README.md` to describe the actual MariaDB + Grafana architecture, removing the InfluxDB/Flux description that no longer matches the code (superseded by ADR-0001).

### Acceptance criteria

- [ ] README describes the MariaDB + Grafana architecture
- [ ] InfluxDB/Flux references removed
- [ ] Configuration instructions (`config.yml.template` usage) remain accurate

---

## Coverage ratchet

**GitHub issue**: [#372](https://github.com/mholubinka1/octopus-monitoring/issues/372)

**Blocked by**: None

**User stories**: 6

### What to build

Replace the fixed `--cov-fail-under=58` gate with a ratchet. A checked-in `.github/coverage-baseline.txt` holds the floor. CI's test step fails if actual coverage drops below it. On `push` events only, a second step reads the actual coverage percentage and, if it exceeds the stored baseline, rewrites the file and commits+pushes it with a `[skip ci]`-tagged message (native GitHub Actions support prevents a retrigger loop). Needs `permissions: contents: write`.

### Acceptance criteria

- [ ] `.github/coverage-baseline.txt` exists, seeded from actual measured coverage at implementation time
- [ ] CI fails if coverage drops below the stored baseline
- [ ] CI auto-commits a raised baseline on `push` events when coverage increases, without retriggering itself
- [ ] `pull_request` runs enforce the gate but never attempt to commit

---

## Pydantic models for config settings

**GitHub issue**: [#373](https://github.com/mholubinka1/octopus-monitoring/issues/373)

**Blocked by**: None

**User stories**: 7

### What to build

Convert `OctopusAPISettings`, `MariaDBSettings`, `RefreshSettings`, `ApplicationSettings` in `common/config.py` from plain classes to `pydantic.BaseModel` subclasses (nested to mirror the YAML shape), constructed via `ApplicationSettings.model_validate(yaml_settings)`.

### Acceptance criteria

- [ ] All four settings classes are `pydantic.BaseModel` subclasses
- [ ] `get_settings()` validates through `model_validate` instead of raw dict indexing
- [ ] A missing/invalid required config field raises a `pydantic.ValidationError` naming the field
- [ ] Unit tests cover both valid YAML producing correct typed settings, and a missing-field case raising a clear validation error

---

## Pydantic models for Octopus API response parsing

**GitHub issue**: [#374](https://github.com/mholubinka1/octopus-monitoring/issues/374)

**Blocked by**: None

**User stories**: 8

### What to build

Define Pydantic models for the Octopus account/meter-information response and the consumption response in `data/octopus/api.py`, validated immediately after `response.json()`. These sit only at the parsing boundary — `api_utils.to_electricity_meter`/`to_gas_meter` and the domain objects (`Account`, `Electricity`, `Gas`, `Consumption`) are unchanged.

### Acceptance criteria

- [ ] Account/meter-information response parsed through a Pydantic model before being mapped to domain objects
- [ ] Consumption response parsed through a Pydantic model before being mapped to `Consumption` objects
- [ ] Existing `responses`-mocked tests continue to pass unchanged (behavior preserved from the caller's perspective)
- [ ] A malformed-response test (missing required field) asserts a clear validation error surfaces instead of a `KeyError`/`AttributeError`

---

## Expand pre-commit hooks

**GitHub issue**: [#375](https://github.com/mholubinka1/octopus-monitoring/issues/375)

**Blocked by**: None

**User stories**: 9

### What to build

Add to `.pre-commit-config.yaml`: `bandit`, `pylint`, `yamllint`, `markdownlint`, `markdown-link-check`, `codespell`, `gitleaks` (default `protect --staged` mode), the standard `pre-commit/pre-commit-hooks` entries (`trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`, `detect-private-key`, `debug-statements`, `check-toml`), and a local `pytest` hook (`language: system`) that runs the suite on every commit. Fix every finding these surface across the existing tree — no blanket suppressions.

### Acceptance criteria

- [ ] All listed hooks present in `.pre-commit-config.yaml`
- [ ] `pre-commit run --all-files` passes clean
- [ ] No finding is suppressed without a documented reason (false positive), and no real issue is silenced

---

## Poetry to uv migration

**GitHub issue**: [#376](https://github.com/mholubinka1/octopus-monitoring/issues/376)

**Blocked by**: [#375](https://github.com/mholubinka1/octopus-monitoring/issues/375)

**User stories**: 10

### What to build

Replace `[tool.poetry]` sections in `pyproject.toml` with PEP 621 `[project]` + `[tool.uv]`; `poetry.lock` → `uv.lock`; rewrite `Dockerfile`'s venv+Poetry install sequence to use `uv`; replace CI's Poetry install steps with `uv`; replace `.pre-commit-config.yaml`'s `poetry-check`/`poetry-lock`/`poetry-export` hooks with the `uv-lock` hook from `astral-sh/uv-pre-commit`, and update the local `pytest` hook to `uv run pytest`; delete `requirements.txt`; change `.github/dependabot.yml`'s `pip` ecosystem entry to `uv`.

### Acceptance criteria

- [ ] `pyproject.toml` uses PEP 621 `[project]` + `[tool.uv]`, no `[tool.poetry]` sections remain
- [ ] `uv.lock` committed, `poetry.lock` and `requirements.txt` removed
- [ ] `Dockerfile` builds successfully using `uv`
- [ ] CI installs dependencies and runs tests via `uv`
- [ ] `.pre-commit-config.yaml` and `.github/dependabot.yml` reference `uv`, not Poetry

---

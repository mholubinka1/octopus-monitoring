# Operational Hygiene

## Problem Statement

The app has several rough edges that make it hard to trust or operate: the consumption refresh loop ignores its own configuration and always polls every 60 seconds; `docker-compose.yml` can't actually start the app (the service is commented out); the README describes an InfluxDB/Grafana architecture that no longer exists in the code; there is no test suite, so any change can silently break behaviour; and there's no way to tell, from outside the logs, whether a scheduled job actually ran successfully.

## Solution

Fix the refresh interval to honour `refresh_interval_hours`, restore the app service in `docker-compose.yml`, rewrite the README to match the real MariaDB-based architecture, add a pytest suite gated into CI before any Docker image is built, and add a `job_run` table so scheduled jobs record their own outcome — the foundation later specs' health panel reads from.

## User Stories

1. As the operator, I want the refresh loop to honour `refresh_interval_hours` from config, so that I can control polling frequency without editing code.
2. As the operator, I want `docker compose up` to actually start the monitoring app alongside MariaDB, so that I don't need undocumented manual steps to run the stack.
3. As a new contributor (or agent), I want the README to describe the actual architecture (MariaDB, not InfluxDB), so that I don't chase a persistence layer that no longer exists.
4. As the operator, I want a test suite that runs in CI before any Docker image is built/pushed, so that broken code doesn't reach the `:dev`/`:latest` image.
5. As the operator, I want every scheduled job to record its outcome, so that later dashboard/health panels can show whether the app is actually working.

## Implementation Decisions

- `app/main.py`: replace the hardcoded `@repeat(every(60).seconds, ...)` with a job registered on `refresh_config.refresh_interval` hours. Register jobs individually rather than one hardcoded repeat, so later specs can add their own jobs (tariff comparison, forecast fetch) on independent cadences using the same `schedule` library.
- `docker-compose.yml`: uncomment/restore the `energy-monitor` app service block. Host-specific volume paths (`/mnt/media/pi-media/...`) are left as-is — this is a personal deployment and paths are user-editable, not something this spec needs to parameterize.
- `README.md`: rewrite to describe the MariaDB + Grafana architecture (superseding the InfluxDB/Flux description per [ADR-0001](../adr/0001-mariadb-over-influxdb.md)).
- New `job_run` table: `id, job_name, status, ran_at, error_message`. Added to `mariadb/init.sql` and `app/data/mysql/sql_models.py`.
- New `MariaDBClient.record_job_run(job_name, status, error=None)` method, following the existing `write_consumption` pattern (`upsert` via `session_write_scope`).
- Wrap the consumption refresh job so its outcome is recorded via `record_job_run`. Later specs (tariff comparison, forecast fetch) reuse this same mechanism for their own jobs — this spec only wires it up for the one job that exists today.
- `pyproject.toml`: add `pytest` and `responses` to the dev dependency group.
- `.github/workflows/ci-arm64.yml`: add a `pytest` step before "Docker Build and Push"; the job must fail fast if tests fail.

## Testing Decisions

- These tests establish the seam patterns later specs reuse: HTTP mocked via `responses`, DB writes tested against a real SQLite in-memory `Session` (not a mocked ORM) — mirrors "mock only at system boundaries" from `.agent-docs/agent.md`.
- Test that the refresh job is registered using the configured interval, not a hardcoded value — extract job registration into a testable function (e.g. `build_schedule(refresh_config, jobs)`) and assert against `schedule`'s job list, or assert the interval value passed to `schedule.every(...)`.
- Test `record_job_run` writes a row via a SQLite in-memory session, covering both success and failure paths.
- No tests for the `docker-compose.yml`/README changes — not code.

## Out of Scope

Any of the new domain features (pricing pipeline, tariff comparison, forecasting, dashboard) — this spec is purely hygiene and test/CI infrastructure. Push notifications or external alerting — job outcomes are recorded to the DB only; a later dashboard spec surfaces them visually.

## Further Notes

This is the foundational branch. `feature/tariff-pricing-pipeline` depends on the test infrastructure and the `job_run` table landing here first.

---

# Part 2: Tooling Modernization

## Problem Statement

Once the CI gate landed (issue #366), several gaps in the tooling itself became visible: the coverage gate is a fixed 58% floor that can silently regress down to that number without anyone noticing; `common/config.py` and the Octopus API response parsing use raw `dict`/`.get()` indexing with no validation, so a malformed `config.yml` or an unexpected API response shape fails with a confusing `KeyError`/`AttributeError` deep in the stack instead of a clear error at the boundary; pre-commit only covers formatting/typing, not security (secrets, known-vulnerable patterns), YAML/Markdown correctness, or spelling; and the project still runs on Poetry, which is slower to install and adds indirection (venv + resolver + build backend) that `uv` collapses into one binary.

## Solution

Turn the fixed coverage floor into a ratchet that can only hold steady or improve. Introduce Pydantic models at the two places raw dicts currently stand in for validated data: config loading and Octopus API response parsing. Expand pre-commit to cover security scanning, YAML/Markdown linting, spelling, and secret detection, fixing whatever it surfaces across the existing tree. Migrate the whole dependency/build toolchain from Poetry to `uv`.

## User Stories

6. As the operator, I want CI's coverage gate to never accept a regression from the last run, so that test coverage only trends up over time, not down.
7. As a developer (or agent), I want `config.yml` validation errors to name the exact missing/invalid field, so that a misconfigured deployment fails fast with a clear message instead of a raw `KeyError`.
8. As a developer (or agent), I want the Octopus API response shapes validated at the parsing boundary, so that an unexpected API response fails with a clear validation error instead of an opaque `AttributeError`.
9. As the operator, I want pre-commit to catch secrets, known security anti-patterns, and spelling/lint issues before they're committed, so that these classes of problems never reach `main`.
10. As the operator, I want the project on `uv` instead of Poetry, so that installs and CI are faster and there's one less layer of indirection to reason about.

## Implementation Decisions

- **Coverage ratchet**: `.github/coverage-baseline.txt` holds a single integer (current measured baseline). CI's test step runs `pytest --cov=app --cov-report=json:coverage.json --cov-fail-under=$(cat .github/coverage-baseline.txt)`. A second CI step, gated to `push` events only (not `pull_request`, to avoid pushing to a ref it doesn't own), reads the actual percentage from `coverage.json`, and if `floor(actual) > baseline`, rewrites the baseline file and commits+pushes it with a `[skip ci]`-tagged message (native GitHub Actions support for that marker prevents a retrigger loop). Needs `permissions: contents: write` on the job.
- **Pydantic config**: `common/config.py`'s `OctopusAPISettings`, `MariaDBSettings`, `RefreshSettings`, `ApplicationSettings` become `pydantic.BaseModel` subclasses (nested to mirror the YAML shape), constructed via `ApplicationSettings.model_validate(yaml_settings)` in `get_settings()`. Plain `BaseModel`, not `pydantic-settings` — the existing flow is YAML-file-only, no env-var override capability was requested.
- **Pydantic API parsing**: in `data/octopus/api.py`, define Pydantic models for the account/meter-information response and the consumption response, validated immediately after `response.json()`. These models sit only at the parsing boundary — `api_utils.to_electricity_meter`/`to_gas_meter` and the existing domain objects (`Account`, `Electricity`, `Gas`, `Consumption`) are unchanged; the Pydantic layer replaces manual `.get()`/`next(iter(...))` parsing, not the domain model.
- **Pre-commit hooks**: add to `.pre-commit-config.yaml` — `bandit`, `pylint`, `yamllint`, `markdownlint`, `markdown-link-check`, `codespell`, `gitleaks` (default `protect --staged` mode, not a full-history scan), and the standard `pre-commit/pre-commit-hooks` entries (`trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`, `detect-private-key`, `debug-statements`, `check-toml`). Add a local `pytest` hook (`language: system`, runs in the project's own env) so the suite runs on every commit, not just in CI. Fix every finding these surface across the existing tree — no blanket suppressions.
- **Poetry → uv**: replace `[tool.poetry]` sections in `pyproject.toml` with PEP 621 `[project]` + `[tool.uv]`; `poetry.lock` → `uv.lock`; `Dockerfile`'s venv+Poetry install sequence replaced with `uv`'s own sync/install flow; CI's `Install Poetry`/`poetry install` steps replaced with `uv` setup; `.pre-commit-config.yaml`'s `poetry-check`/`poetry-lock`/`poetry-export` hooks replaced with the `uv-lock` hook from `astral-sh/uv-pre-commit`; `requirements.txt` deleted (no longer generated); `.github/dependabot.yml`'s `pip` ecosystem entry changed to `uv`. See [ADR-0004](../adr/0004-poetry-to-uv-migration.md).

## Testing Decisions

- Continues the seams already established in Part 1: HTTP mocked via `responses`, DB writes tested against a real SQLite in-memory `Session`. No new seams introduced.
- Config Pydantic models: unit tests asserting valid YAML produces the expected typed settings, and that a missing/invalid required field raises a `pydantic.ValidationError` with a message naming the field — extending the existing `common.config` test surface (currently untested; this is new coverage, not a rewrite of existing tests).
- API response Pydantic models: existing `test_consumption_seam.py`-style tests continue to mock HTTP and assert on the resulting domain objects — behavior is unchanged from the caller's perspective. Add one test per response model for the malformed-response case (missing required field) asserting a clear validation error surfaces instead of a `KeyError`/`AttributeError`.
- Coverage ratchet: no pytest seam — the bash/CI logic is verified by running it (a real `push` to the branch) and inspecting the workflow run and the resulting baseline-file commit.
- Pre-commit hooks and the uv migration: no pytest seam — verified by `pre-commit run --all-files` passing clean and `uv run pytest` / `docker build` succeeding locally.

## Out of Scope

Domain model conversion to Pydantic (Account, Meter, Agreement, Consumption) — explicitly decided against; see design session notes. `pydantic-settings`/env-var config overrides. A full `gitleaks` git-history scan (only staged-diff protection is added). Backfilling legacy test coverage to hit 80% — tracked separately in [#371](https://github.com/mholubinka1/octopus-monitoring/issues/371).

## Further Notes

This part depends on Part 1 having landed (it did — issues #366-#370 are implemented and committed on this branch, code-review passed). The coverage ratchet's initial baseline value should be set from the actual measured coverage at implementation time, not copied from this document.

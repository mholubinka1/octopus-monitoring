# Consolidate MariaDB deployment credentials into a minimal .env

## Problem Statement

Setting up a new deployment currently means hand-filling two separate credential
files that overlap: `.env` (`MARIADB_USER`, `MARIADB_PASSWORD`, `MARIADB_DATABASE`,
`MARIADB_RANDOM_ROOT_PASSWORD`) and `config.yml` (`mariadb.username`, `password`,
`database`, plus host/port). Two of the four `.env` fields are pure duplicates of
`config.yml` values, and one (`MARIADB_RANDOM_ROOT_PASSWORD`) isn't a secret at all —
it's a fixed boolean toggle that never needed to be configurable per deployment. This
was discovered while preparing a fresh deployment for the user's Raspberry Pi, where
both files had to be filled in with the same MariaDB username/password.

## Solution

Shrink `.env` to only the fields that are mechanically required and don't already
live elsewhere: `MARIADB_USER` and `MARIADB_PASSWORD` (the app's MariaDB account,
bootstrapped into the database on the container's first boot). Move
`MARIADB_DATABASE` and `MARIADB_RANDOM_ROOT_PASSWORD` into `docker-compose.yml`
itself as hardcoded values, consistent with the compose file's existing
"host-specific — edit for your deployment" bind-mount paths. Document, in the
README, that `.env`'s `MARIADB_USER`/`MARIADB_PASSWORD` must match `config.yml`'s
`mariadb.username`/`password` — and why that duplication remains rather than being
engineered away.

## User Stories

1. As someone standing up a new deployment, I want to fill in as few credential
   fields as possible, so that I don't have to keep two files in sync by hand for
   values that don't need to vary independently.
2. As someone reading `.env.template` for the first time, I want it to contain only
   fields that are actually secrets or genuinely need to vary per deployment, so
   that I'm not asked to make a decision (e.g. "should root password be random?")
   that was already made for me.
3. As a future reader of this repo (human or agent), I want the README to explain
   why `.env` still exists at all alongside `config.yml`, and why its
   username/password must match `config.yml`'s, so that this isn't mistaken for
   leftover duplication that should be "cleaned up" again later.

## Implementation Decisions

- **`.env.template`**: trim to exactly two lines, `MARIADB_USER=` and
  `MARIADB_PASSWORD=`. Remove `MARIADB_DATABASE` and
  `MARIADB_MYSQL_LOCALHOST_USER` fields (the latter is unused by
  `docker-compose.yml` today — confirmed by grep — so it is dropped, not moved).
- **`docker-compose.yml`** (`mariadb` service `environment` block):
  - `MARIADB_RANDOM_ROOT_PASSWORD: 1` — hardcoded literal, no longer sourced from
    `.env`. Root credentials are never used post-bootstrap (the app connects as
    its own `MARIADB_USER`), so there is nothing to keep secret here.
  - `MARIADB_DATABASE: octopus` — hardcoded literal, matching `config.yml`'s
    `mariadb.database` value. Consistent with the file's existing pattern of
    host-specific literals a deployer edits directly (e.g. the bind-mount paths).
  - `MARIADB_USER: ${MARIADB_USER}` and `MARIADB_PASSWORD: ${MARIADB_PASSWORD}`
    remain, sourced from `.env` as today.
- **No changes to `app/common/config.py` or `config.yml.template`** — the app
  continues to read `mariadb.username`/`password` from `config.yml` exactly as
  today; introducing environment-variable support into the Python config loader
  was considered and rejected (see ADR-0006) because it would only move the
  duplication, not remove it, while adding new code surface.
- **README**: add a line to the Configuration section stating that `.env`'s
  `MARIADB_USER`/`MARIADB_PASSWORD` must match `config.yml`'s
  `mariadb.username`/`password`, and that `.env` is consumed only once — at the
  MariaDB container's first boot, to create that user — not read again afterward.
- **New ADR** (`0006-minimal-env-file-over-config-yml-only.md`) recording why a
  two-line `.env` remains alongside `config.yml` rather than eliminating it: Docker
  Compose only substitutes variables from a `.env`-style file, and MariaDB's own
  user-bootstrap mechanism only has access to the (discarded) root session during
  that same first-boot window — so the two genuinely-required fields cannot be
  sourced from `config.yml` without either a custom `docker-entrypoint-initdb.d`
  script that scrapes YAML, or new environment-variable support in the Python app.
  Both alternatives were considered and rejected in favour of keeping the overlap
  to its practical minimum instead.

## Testing Decisions

This is an infrastructure/deployment-config change — no application code path is
touched (confirmed: no existing test references `docker-compose.yml`, `.env`, or
`MARIADB_USER`/`MARIADB_RANDOM_ROOT_PASSWORD`; `app/common/config.py`'s
`MariaDBSettings` model and its fields are unchanged). There is no unit-testable
seam to add a BDD scenario against. Verification is integration-level: the
already-planned real deployment to the user's Raspberry Pi (`pi-desktop`), run
immediately after this chore merges, using the new two-line `.env` and updated
`docker-compose.yml` to confirm the MariaDB container bootstraps the app user
correctly and the app connects, syncs its schema, and writes consumption data.

## Out of Scope

- Adding environment-variable override support to `app/common/config.py`.
- Any change to `config.yml.template`'s fields (they are already correct and
  unchanged).
- Any change to `mariadb/init.sql` (still solely responsible for
  `CREATE DATABASE IF NOT EXISTS octopus;`, per ADR-0005's collapse).
- Folding the resulting `docker-compose.yml` into `pi-desktop/docker/docker-compose.yml`
  — that happens after this chore merges and the standalone deployment test passes,
  per the user's explicit sequencing.

## Further Notes

This chore was surfaced mid-session while preparing the first real deployment of
`octopus-monitoring` to the user's Raspberry Pi (`pi-desktop`), where the existing
local (gitignored) `.env` and `config.yml` were found to duplicate the same
MariaDB username/password. The Pi deployment test was paused so this could go
through the full `/implement` pipeline rather than be hand-edited ad hoc, per the
user's established preference (see prior handoff notes on the schema-sync chore).

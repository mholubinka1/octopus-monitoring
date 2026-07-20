# Issues: chore-consolidate-mariadb-env-config

## Trim .env to MariaDB app-user credentials only; document the config split (#393)

**Blocked by**: None

**User stories**: 1, 2, 3, 4

### What to build

Shrink `.env`/`.env.template` to the two fields that are mechanically required and
don't already live in `config.yml`: `MARIADB_USER` and `MARIADB_PASSWORD`. Move
`MARIADB_DATABASE` and `MARIADB_RANDOM_ROOT_PASSWORD` into `docker-compose.yml`'s
`mariadb` service as hardcoded literals (`octopus` and `1` respectively) — neither
is a secret, and both already have counterparts documented as
host-specific/edit-for-your-deployment elsewhere in that file. Drop
`MARIADB_MYSQL_LOCALHOST_USER` and `MARIADB_ROOT_PASSWORD` entirely — both are
unused by `docker-compose.yml` today (it only ever referenced the distinct
`MARIADB_RANDOM_ROOT_PASSWORD`, now hardcoded). Add lines to the README's Configuration section explaining that `.env`'s
`MARIADB_USER`/`MARIADB_PASSWORD` must match `config.yml`'s
`mariadb.username`/`password`, and that while Compose passes these values into the
container on every start, MariaDB's entrypoint only acts on them once — at first
boot, to create that user — so changing `.env` afterward won't rotate an
already-created user's password. Also note `config.yml`'s `mariadb.database` must be
`octopus` to match the hardcoded value. Also replace the README's brief `## Running`
note with a detailed first-time deployment walkthrough and a separate
subsequent-deployments section (added mid-session at the user's explicit request,
ahead of the app's first real deployment).

### Acceptance criteria

- [x] `.env.template` contains exactly `MARIADB_USER=` and `MARIADB_PASSWORD=`
      (no other fields).
- [x] `docker-compose.yml`'s `mariadb` service environment block no longer
      references `${MARIADB_DATABASE}` or `${MARIADB_RANDOM_ROOT_PASSWORD}` — both
      are hardcoded literals.
- [x] README documents the `.env`/`config.yml` must-match relationship (including
      the `database: octopus` requirement) and the first-boot-only caveat.
- [x] README has a detailed first-time deployment walkthrough and a subsequent
      deployments section (updates, config changes, restarts).
- [x] `docker compose config` validates cleanly against the trimmed `.env.template`
      (copied to `.env` with placeholder values).

---

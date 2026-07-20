# Issues: chore-consolidate-mariadb-env-config

## Trim .env to MariaDB app-user credentials only; document the config split (#393)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Shrink `.env`/`.env.template` to the two fields that are mechanically required and
don't already live in `config.yml`: `MARIADB_USER` and `MARIADB_PASSWORD`. Move
`MARIADB_DATABASE` and `MARIADB_RANDOM_ROOT_PASSWORD` into `docker-compose.yml`'s
`mariadb` service as hardcoded literals (`octopus` and `1` respectively) — neither
is a secret, and both already have counterparts documented as
host-specific/edit-for-your-deployment elsewhere in that file. Drop
`MARIADB_MYSQL_LOCALHOST_USER` entirely — it's unused by `docker-compose.yml`
today. Add a line to the README's Configuration section explaining that `.env`'s
`MARIADB_USER`/`MARIADB_PASSWORD` must match `config.yml`'s
`mariadb.username`/`password`, and that `.env` is read only once, at the MariaDB
container's first boot.

### Acceptance criteria

- [ ] `.env.template` contains exactly `MARIADB_USER=` and `MARIADB_PASSWORD=`
      (no other fields).
- [ ] `docker-compose.yml`'s `mariadb` service environment block no longer
      references `${MARIADB_DATABASE}` or `${MARIADB_RANDOM_ROOT_PASSWORD}` — both
      are hardcoded literals.
- [ ] README documents the `.env`/`config.yml` must-match relationship and the
      first-boot-only caveat.
- [ ] `docker compose config` validates cleanly against the trimmed `.env.template`
      (copied to `.env` with placeholder values).

---

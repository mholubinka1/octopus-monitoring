---
status: accepted
---

# Keep a minimal `.env` alongside `config.yml` rather than eliminating it

`.env` and `config.yml` both held the MariaDB app-user credentials, discovered as
duplication while preparing the first real Pi deployment. Docker Compose only
substitutes variables from a `.env`-style file — it cannot parse `config.yml`
directly — and MariaDB's own user-bootstrap mechanism only has access to a root
session during the container's one-time first-boot window, after which a random
root password is discarded, so nothing outside that window (including the Python
app, which has no root credentials) can create the app's database user. Two real
alternatives were considered: a custom `docker-entrypoint-initdb.d` script that
scrapes `config.yml`'s `mariadb:` block at first boot, and adding
environment-variable override support to `app/common/config.py` so both
containers could source credentials from one place. Both were rejected as
engineering more surface than the problem warrants for a single-deployment repo.
Instead, `.env` was trimmed to only the two fields that are mechanically required
and don't already live elsewhere (`MARIADB_USER`, `MARIADB_PASSWORD`); everything
else duplicated or non-secret (`MARIADB_DATABASE`, `MARIADB_RANDOM_ROOT_PASSWORD`)
moved to hardcoded literals in `docker-compose.yml`.

## Consequences

- `.env`'s `MARIADB_USER`/`MARIADB_PASSWORD` must still be kept in sync by hand
  with `config.yml`'s `mariadb.username`/`password` — this ADR is why that
  duplication is deliberate and minimal, not an oversight to "clean up" again.
- `.env` is read only once, at the MariaDB container's first boot (when its data
  directory is first initialized) — changing it after a volume already has data
  has no effect, matching the same "first-boot only" caveat `mariadb/init.sql`
  already has under ADR-0005.

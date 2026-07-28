# Local-day bucketing: Python (zoneinfo) in app code, CONVERT_TZ in Grafana queries

`consumption.period_from`/`period_to` are corrected to true UTC (fixing a bug where Octopus's local-BST-offset consumption timestamps were persisted with the offset silently dropped). Every "group by day" calculation must therefore convert to Europe/London local time before bucketing, to match Octopus's own daily cost/consumption reporting.

App-side code (`MariaDBClient.read_elapsed_billing_period_costs`, `read_consumption_summarization_window`) buckets by local calendar day using Python's `zoneinfo.ZoneInfo("Europe/London")` on fetched rows, rather than `CONVERT_TZ(...)` in the SQL query. `tests/conftest.py`'s `mariadb_client` fixture runs against SQLite, which has no `CONVERT_TZ` equivalent — an SQL-side approach would require replacing that fixture with a real MariaDB test double for these two queries alone. Data volumes here are small (bounded by the 45-day raw-retention window, or a year of daily summaries), so pulling rows into Python for bucketing is cheap.

The standalone `grafana/mariadb/queries.md` reference queries use `CONVERT_TZ(period_from, 'UTC', 'Europe/London')` directly, since that file only ever runs against real MariaDB via Grafana's query editor — no SQLite constraint applies, and keeping aggregation in SQL there avoids pulling raw rows through Grafana's query layer.

---
status: accepted
---

# Use MariaDB + Grafana, retire InfluxDB

The original README described InfluxDB as the persistence layer with Grafana querying it via Flux, but the codebase had already drifted to MariaDB/SQLAlchemy as the only actively-written store — the InfluxDB client lived on unused under `app/_deprecated/`. We decided to formally commit to MariaDB and delete the InfluxDB code rather than revive it, because Grafana's native MySQL data source covers the dashboard need without running two datastores, and continuing to maintain dead InfluxDB code that contradicted the actual write path was actively misleading to future readers (human or agent).

## Considered Options

- **Revert to InfluxDB** (the original plan): purpose-built for time-series and nicer Flux queries, but would require reviving `app/_deprecated/influx.py`, dropping the MariaDB ORM layer, and running/maintaining a second datastore for no functional gain over Grafana-on-MySQL.
- **Run both**: rejected outright — doubles write paths and operational surface for a single-user household app.

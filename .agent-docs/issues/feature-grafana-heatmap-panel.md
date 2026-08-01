# Issues: feature/grafana-heatmap-panel

## Rewrite Consumption Heatmap panel as native Grafana Heatmap

**GitHub issue**: #456

**Blocked by**: None

**User stories**: 1, 2, 3, 4, 5

### What to build

In `grafana/mariadb/queries.md`, replace the Consumption Heatmap panel's long-format query (`day_of_week`, `hour_of_day`, `avg_kwh` — one row per weekday/hour pair, which Grafana's Heatmap panel cannot render) with a wide-format query: one row per hour-of-day (a real `DATETIME`, so the field is time-typed and drives the X axis natively) and one column per weekday (`Monday` through `Sunday`, each `AVG(est_kwh)` over a 45-day trailing window). Grafana's Heatmap panel, with `Calculate from data: Off`, treats the first time-typed field as X and every other numeric field as its own Y-axis row — no transform, no schema change, no version upgrade needed.

Also rewrite the panel's heading/window label and add explanatory prose: why the wide-format shape works natively with the Heatmap panel, why the panel matters (the only panel showing day-of-week and hour-of-day together), the 45-day window rationale (matches `consumption`'s actual backfill retention, self-contained since the shared "Row 2 lookback windows" paragraph belongs to separate, out-of-scope bugfix work), the `kWh` field-unit override via a name-regex across the seven weekday columns, and a note to check the Y-Axis Reverse toggle if Monday doesn't render as the top row.

### Acceptance criteria

- [ ] Query is wide-format: first column `time` (real `DATETIME` via `TIMESTAMP(CURDATE()) + INTERVAL HOUR(...) HOUR`), seven weekday columns (`Monday`...`Sunday`), each `ROUND(AVG(CASE WHEN DAYNAME(...) = '<day>' THEN est_kwh END), 4)`, grouped by hour, ordered by time.
- [ ] Window is `NOW() - INTERVAL 45 DAY`, not 90 days.
- [ ] NULL cells (no matching rows for a weekday/hour combination) are left as NULL, not `COALESCE`d to 0.
- [ ] Panel heading updated to reflect the native Heatmap type and the 45-day window (not "table, colored cells" — this branch never had that workaround; not "90-Day Window").
- [ ] Prose explains: the wide-format `Calculate: Off` mechanism (first time field = X, each other numeric field = its own Y row), why this panel matters, the 45-day window rationale, the `kWh` unit override via field override, and the Reverse-toggle note for row order.
- [ ] No changes to any other panel, the shared conventions section, or the "Row 2 lookback windows" paragraph (out of scope — tracked on the separate bugfix branch).

---

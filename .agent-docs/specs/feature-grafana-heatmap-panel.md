# Native Consumption Heatmap Panel

## Problem Statement

The "Consumption Heatmap — Hour × Day-of-Week" panel in `grafana/mariadb/queries.md` is documented as a native Grafana Heatmap panel, but its query returns a long-format shape (`day_of_week`, `hour_of_day`, `avg_kwh`, one row per weekday/hour pair) that Grafana's Heatmap panel cannot render — the panel has no field-mapping option that accepts two categorical axes. The user wants this panel to actually work as a real Heatmap, not a workaround (e.g. a colored Table), so they can see at a glance which hours and days of the week their electricity consumption peaks — the only panel on the dashboard showing day and hour together instead of collapsing one dimension away.

## Solution

Rewrite the panel's query into the wide-format shape Grafana's Heatmap panel (`Calculate from data: Off`) natively accepts: one row per hour-of-day (a real `DATETIME`, so the field is time-typed and renders `00:00`–`23:00` axis ticks for free) with one column per weekday (`Monday`...`Sunday`), each cell an `AVG(est_kwh)` over a 45-day trailing window. Grafana treats the first time-typed field as the X axis and every other numeric field as its own Y-axis row, labelled by its column name — confirmed against Grafana's own dataplane-contract docs and the deployed 10.4.2 panel's source, and written up in `.agent-docs/research/grafana-heatmap-panel.md`. No schema change, no new table, no Grafana version upgrade, no transform — this is a query-shape and panel-config fix contained entirely to one panel's SQL and documentation.

## User Stories

1. As the dashboard owner, I want the Consumption Heatmap panel to render as an actual Grafana Heatmap (not a table), so that the weekly usage pattern reads visually the way a heatmap is meant to — color intensity by cell, not a grid of numbers.
2. As the dashboard owner, I want Monday to render at the top row and Sunday at the bottom, so that the panel reads top-to-bottom in calendar order rather than an arbitrary or reversed order.
3. As the dashboard owner, I want the panel's window to honestly reflect how much history it actually draws on (45 days, not 90), so the panel doesn't imply it's using more data than `consumption`'s effective retention actually provides.
4. As the dashboard owner, I want a weekday/hour cell with zero matching readings in the window to render as an empty gap rather than a false zero, so the panel never implies confirmed no-usage where there's actually no data.
5. As a future reader of `queries.md`, I want the panel's prose to explain *why* the wide-format query works natively with the Heatmap panel (superseding the old, incorrect assumption that categorical axes aren't supported at all), so nobody re-litigates or reverts this by accident.

## Implementation Decisions

- **File touched**: `grafana/mariadb/queries.md` only. No application code, dashboard JSON, or provisioning file exists in this repo for Grafana panels — this file is hand-copied into Grafana's query editor per its own header, so it's the sole artifact.
- **Query shape**: transpose from long format (`day_of_week`, `hour_of_day`, `avg_kwh`) to wide format:
  - First column: `time`, a real `DATETIME` anchored to `TIMESTAMP(CURDATE()) + INTERVAL HOUR(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) HOUR` — the date component is arbitrary (always "today"), only the hour-of-day matters, but the field must be time-typed for Grafana to treat it as the X axis and render hour ticks natively.
  - Seven further columns, one per weekday (`Monday` through `Sunday`), each `ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = '<day>' THEN est_kwh END), 4)`.
  - `GROUP BY HOUR(CONVERT_TZ(period_from, 'UTC', 'Europe/London'))`, `ORDER BY time`.
  - `WHERE energy = 'E' AND period_from >= NOW() - INTERVAL 45 DAY` — changed from the existing 90-day window. `consumption`'s startup backfill only ever pulls `retention_days` (45) of history (see `.agent-docs/context.md`'s **Retention Window** entry), so a 90-day window here would silently return less data than it claims. This panel's fix stands alone: the file's other Row 2 panels still say 90/84 days as of this branch's base — that's separately tracked bugfix work, out of scope here. This panel gets a self-contained note explaining the 45-day choice rather than pointing at a shared "Row 2 lookback windows" paragraph that doesn't exist on this branch.
  - No completeness-guard `HAVING` clause — not needed here (each cell already averages twelve or fourteen same-weekday-same-hour samples spread across the window — `consumption` is half-hourly, and 45 days gives each weekday six or seven occurrences — unlike the daily-total panels the guard protects).
  - No `${region}` variable — panel only reads `consumption`, no join to `product_rate`/`agreement`.
  - NULL cells (a weekday/hour combination with zero matching rows) stay NULL, not `COALESCE`d to 0 — consistent with how `AVG(CASE WHEN ...)` already behaves elsewhere in this file, and avoids implying confirmed zero usage.
- **Panel config** (documented in prose, since there's no dashboard JSON to change): native Heatmap panel, `Calculate from data: Off`. Field roles are implicit (no field-mapping UI exists for this data shape) — first time-typed field becomes X axis, each of the seven weekday fields becomes its own Y-axis row named after its column. Apply the `kWh` custom unit (per the file's existing Field-formatting convention) via a field override with a name-regex covering the seven weekday columns. If Monday doesn't render as the top row (per user story 2), the panel's Y-Axis **Reverse** toggle fixes it without any query change — call this out explicitly as something to check visually once built, since it isn't resolvable from Grafana's docs or source alone.
- **Prose rewrite**: replace the panel's current absence of prose (it currently has none — the original long-format query has no explanation) with a paragraph covering: why the wide-format query is the shape Grafana's Heatmap panel actually wants (`Calculate: Off` treats the first time-typed field as X, every other numeric field as its own Y-axis row — this is documented Grafana behaviour, not a workaround), why this panel matters (the only panel showing day-of-week and hour-of-day together, motivating load-shifting against Agile's time-of-day pricing), and the 45-day-window rationale above.

## Testing Decisions

This is a documentation-only change to a Markdown file containing reference SQL — there is no application code, no test suite, and no CI surface for Grafana panel definitions in this repo. Verification is manual: the user pastes the query into Grafana's query editor and confirms the panel renders correctly (per the "Docs only, verify separately" decision made during grilling). No automated test is applicable or in scope.

## Out of Scope

- The 90-day/84-day windows on this file's other Row 2 panels (`p/kWh Efficiency`, `Day-of-Week Average Consumption`, both 7-Day Rolling Average panels) — tracked separately on `bugfix/grafana-query-slow-cost-join`.
- The `product_rate` join-performance fix and the shared "Row 2 lookback windows are capped..." explanatory paragraph — also on the separate bugfix branch; not duplicated here.
- Any Grafana version upgrade or new `Transpose`/`Pivot` transform — confirmed unnecessary for this fix (`.agent-docs/research/grafana-heatmap-panel.md` §3b).
- A new materialized table + daily job — confirmed viable as a future fallback if the live query proves too slow, but not needed now (`.agent-docs/research/grafana-heatmap-panel.md` §3c).
- Actually applying/verifying the panel in the live Grafana instance — the user will do this separately after the doc change lands.

## Further Notes

Full research backing this approach, including primary-source citations (Grafana's dataplane contract docs, the 10.4.2 panel source, release notes, and community precedent) lives in `.agent-docs/research/grafana-heatmap-panel.md`.

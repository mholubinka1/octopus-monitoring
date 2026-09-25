# Issues: feature-daily-avg-unit-price-chart

> Work complete — PR ready to merge.

## Add Daily Average Unit Price (Rolling 7-Day Window) panel

**GitHub issue**: [#518](https://github.com/mholubinka1/home-monitoring/issues/518)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

A new Grafana panel, "Daily Average Unit Price (Rolling 7-Day Window)", showing the consumption-weighted price actually paid per kWh each day (excluding standing charge), smoothed over a trailing 7-day window, covering the same Last 45 Days scope and query conventions (local-day bucketing, day-completeness guard, correlated-subquery `product_rate` join) as the existing Daily Average Cost and Daily Average Usage panels. Electricity only. Added to the dashboard grid row leftmost of the three (Unit Price → Cost → Usage, left to right), which requires narrowing both siblings to make room. Reuses the Agile Prices panel's `p/kwh` unit and threshold styling for visual consistency.

Building this required first reconciling `grafana/dashboard.json` and `grafana/mariadb/queries.md` against a fresh live export of the dashboard, which had drifted significantly (17 unreconciled manual edits) since the files were last synced — including one real regression found in that live export (a documented query performance fix that had been accidentally reverted there), which was corrected back to the form already present in the repo's committed file as part of this same change.

### Acceptance criteria

- [x] New panel shows a 7-day rolling average of consumption-weighted daily unit price (p/kWh), Electricity only, over the last 45 days
- [x] Panel sits visually grouped with Daily Average Cost and Daily Average Usage in the same row (order: Unit Price, Cost, Usage), all three fitting the row without overlap
- [x] Panel styling (unit, threshold bands) matches the existing Agile Prices panel's `p/kwh` convention; `decimals`/`min` are set explicitly on the new panel (Agile Prices leaves both unset)
- [x] `grafana/dashboard.json` matches the current live dashboard export, with the Latest Consumption panel's `product_rate` join confirmed in its documented fixed (correlated-subquery) form
- [x] `grafana/mariadb/queries.md` documents the new panel and every other change found during reconciliation

---

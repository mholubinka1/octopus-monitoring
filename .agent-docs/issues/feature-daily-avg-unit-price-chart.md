# Issues: feature-daily-avg-unit-price-chart

## Add Daily Average Unit Price (Rolling 7-Day Window) panel

**GitHub issue**: [#518](https://github.com/mholubinka1/octopus-monitoring/issues/518)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

A new Grafana panel, "Daily Average Unit Price (Rolling 7-Day Window)", showing the consumption-weighted price actually paid per kWh each day (excluding standing charge), smoothed over a trailing 7-day window, covering the same Last 45 Days scope and query conventions (local-day bucketing, day-completeness guard, correlated-subquery `product_rate` join) as the existing Daily Average Cost and Daily Average Usage panels. Electricity only. Placed between those two sibling panels in the dashboard grid, which requires narrowing both to make room. Reuses the Agile Prices panel's `p/kwh` unit and threshold styling for visual consistency.

Building this required first reconciling `grafana/dashboard.json` and `grafana/mariadb/queries.md` against a fresh live export of the dashboard, which had drifted significantly (17 unreconciled manual edits) since the files were last synced — including one real regression (a documented query performance fix that had been accidentally reverted), which was restored as part of this same change.

### Acceptance criteria

- [ ] New panel shows a 7-day rolling average of consumption-weighted daily unit price (p/kWh), Electricity only, over the last 45 days
- [ ] Panel sits visually between Daily Average Cost and Daily Average Usage, all three fitting the row without overlap
- [ ] Panel styling (unit, thresholds, decimals) matches the existing Agile Prices panel's `p/kwh` convention
- [ ] `grafana/dashboard.json` matches the current live dashboard export, with the one identified performance regression (Latest Consumption panel's `product_rate` join) restored to its documented fixed form
- [ ] `grafana/mariadb/queries.md` documents the new panel and every other change found during reconciliation

---

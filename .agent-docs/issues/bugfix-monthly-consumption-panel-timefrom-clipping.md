# Issues: bugfix-monthly-consumption-panel-timefrom-clipping

> Work complete — PR ready to merge.

## Widen timeFrom on Monthly Total Consumption and Weekly YoY panels (#474)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

`grafana/dashboard.json` panel id 9 ("Monthly Total Consumption") and panel id 10 ("Consumption Year-on-Year Percentage Change") both have their `timeFrom` override widened from `365d` to `400d`, since each panel's underlying query has a calendar-based lookback (11 months / 52-53 ISO weeks) that can reach up to 366 days and was being clipped by the fixed 365-day axis window. `grafana/mariadb/queries.md`'s documentation for both panels is updated to match, with a note explaining why the value is wider than the nominal ~365-day lookback.

This is a single end-to-end vertical slice: the panel config change and its documentation are inseparable, and there's no automated test seam for either (Grafana dashboard JSON and its reference doc, consistent with other Grafana-only fixes in this repo).

### Acceptance criteria

- [x] `dashboard.json` panel id 9's `timeFrom` is `400d`
- [x] `dashboard.json` panel id 10's `timeFrom` is `400d`
- [x] `grafana/mariadb/queries.md` documents `400d` for both panels with the rationale
- [x] No SQL query changes — both queries were already correct
- [x] Verified visually in Grafana once deployed: oldest month's bar / oldest week's point renders fully, not clipped

---

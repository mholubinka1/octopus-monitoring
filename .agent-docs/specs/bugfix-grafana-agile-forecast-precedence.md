# Agile Prices Panel: Actual-Rate Precedence Over Stale Forecast

## Problem Statement

The "Agile Prices: Today/Tomorrow (Actual + Forecast)" Grafana panel (id 3) can plot two
conflicting price lines for the same half-hour slot: one from `product_rate` (Octopus's
own published Agile rate, tagged `actual`) and one from `agile_forecast` (AgilePredict's
cached prediction, tagged `forecast`). Whenever both tables hold a row for the same
`period_from`/`valid_from`, the panel shows both, which reads as noisy or contradictory
data rather than a single coherent price line.

This is not an edge case: AgilePredict's cached forecast spans a rolling ~14-day horizon,
while Octopus only publishes real Agile rates ~1-2 days ahead, so the two datasets
routinely overlap for today/tomorrow, and the overlap can be large after a stale
forecast refresh (confirmed live on the production Pi: a 34-hour-stale forecast row
showed `-1.14p` actual vs `21.94p` forecast for the identical timestamp).

## Solution

Give Octopus's own published rate precedence: whenever `product_rate` already has a row
for a half-hour, the panel suppresses the `agile_forecast` row for that same half-hour.
The `actual`/`forecast` series distinction in the legend is preserved — only the
overlapping duplicate is removed, not the actual/forecast split itself.

This mirrors an already-shipped pattern in the same dashboard: the "Cheapest Time
Window" panel (id 13) already applies actual-rate precedence over forecast rates via a
`NOT EXISTS` filter, so this change brings panel id 3 in line with the convention id 13
already established, rather than introducing a new one.

## User Stories

1. As the dashboard viewer, I want the Agile Prices panel to show one rate per
   half-hour, so that I'm not confused by two contradictory lines for the same time slot.
2. As the dashboard viewer, I want to still be able to tell which portion of the line is
   Octopus's confirmed rate versus AgilePredict's forecast, so that I know how much to
   trust each part of the curve.
3. As the operator, I want the fix to follow the same precedence approach already used
   elsewhere in this dashboard, so that the two `agile_forecast`-reading panels behave
   consistently and future readers only need to learn the pattern once.

## Implementation Decisions

- **Scope confirmed via grep**: only two panels read `agile_forecast` in this dashboard —
  id 3 (the one being fixed) and id 13 (Cheapest Time Window, already correct). No other
  panel needs a change.
- **Query change (panel id 3, both `grafana/mariadb/queries.md` and the matching
  `rawSql` in `grafana/dashboard.json`)**: keep the existing two-branch `UNION ALL`
  structure as-is (no rewrite to id 13's CTE style — deliberately the smaller diff for a
  panel that has otherwise stayed a plain two-branch query). Add one `NOT EXISTS`
  predicate to the forecast branch's `WHERE` clause, keyed on an exact match against
  `product_rate` for the same product/region/half-hour:

  ```sql
  AND NOT EXISTS (
    SELECT 1 FROM product_rate pr2
    WHERE pr2.product_code = (
      SELECT product_code FROM agreement
      WHERE energy = 'E'
        AND valid_from <= NOW()
        AND NOW() < COALESCE(valid_to, '9999-12-31 23:59:59')
      ORDER BY valid_from DESC LIMIT 1
    )
    AND pr2.region = '${region}'
    AND pr2.valid_from = agile_forecast.period_from
  )
  ```

  The actual branch's own bounds (`valid_from >= CURDATE()`) and the forecast branch's
  own bounds (`period_from >= NOW()`) are unchanged — only the new `NOT EXISTS` clause is
  added.
- **Doc prose update (`queries.md` only)**: panel id 3's description currently says
  nothing about precedence. Add a sentence describing the new dedup behaviour, matching
  how panel id 13's description already documents its own precedence filter.
- No Python/application code changes, no schema changes, no migration. This is a
  dashboard-query-only fix.

## Testing Decisions

- This dashboard area has no automated test suite (confirmed: `tests/` has no
  Grafana-query coverage, and every prior Grafana query fix in this repo's history was
  verified by running the corrected SQL live against the production/staging database,
  not via a written test). Verification for this change follows the same prior art:
  run the corrected query directly against the Pi's `energy-monitor-db` and confirm no
  timestamp appears twice across `actual`/`forecast` series.
- Confirm `queries.md`'s SQL block and `dashboard.json`'s `rawSql` for panel id 3 remain
  byte-for-byte identical after the edit (existing repo convention, per the "Add Grafana
  dashboard JSON export and resync queries.md" commit).

## Out of Scope

- Fixing AgilePredict's own staleness/timeout issue (external outage, self-heals at the
  next scheduled `cost_forecast_refresh` run; not a code defect in this repo).
- Any change to panel id 13 (Cheapest Time Window) — already correct.
- Any change to `agile_forecast`'s retention, refresh cadence, or job-run retry policy.
- Collapsing the `actual`/`forecast` series distinction into a single series.

## Further Notes

Diagnosed via a live query against the production Pi (`ssh pi@pi-desktop`,
`energy-monitor-db` container, region `C`), which reproduced the exact duplication
described in the Problem Statement before any code changes were made.

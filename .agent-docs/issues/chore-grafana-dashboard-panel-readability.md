# Issues: chore-grafana-dashboard-panel-readability

> Work complete — PR ready to merge.

## Monthly/Weekly panels get a real time axis (#446)

**Blocked by**: None

**User stories**: 1, 2

### What to build

In `grafana/mariadb/queries.md`, fix the four panels currently labeled "time series" whose queries group by a value Grafana can't treat as a real time axis: Monthly Total Consumption (Electricity + Gas) groups by a `DATE_FORMAT(...)` string like "Jul 2026"; Weekly Year-on-Year Change (Electricity + Gas) groups by an integer `YEARWEEK`. Replace the displayed x-axis column in all four with a real date aliased `time` — first-of-month for the monthly panels, the Monday that ISO week begins on for the weekly panels (`yearweek` stays available internally for the existing CTE joins, just isn't the displayed column anymore). Drop the string-formatted label column entirely; Grafana derives axis tick labels from the date itself, matching every other time-series panel already in this file.

### Acceptance criteria

- [x] All four panels' queries return a `time` column of a real date type, not a string or integer.
- [x] Weekly YoY panels' `time` value is the Monday of that ISO week.
- [x] Existing week-53 fallback and completeness-guard (`HAVING COUNT(*) = 7`) logic is preserved unchanged.
- [x] Each of the four queries executed read-only against production MariaDB and returns rows without error, ordered correctly by `time`.

---

## Cheapest N-Hour Window unpivot (#447)

**Blocked by**: None

**User stories**: 3

**Bonus fixes found via verification** (not in the original spec, approved mid-implementation): `product_rate` has no `period_from` column (only `valid_from`/`valid_to`) — this query and the Price Curve panel above it both referenced it and would have errored in Grafana. Also, both panels' "current agreement" lookup used `valid_to IS NULL`, which returns zero rows for electricity today since this account's E agreements always carry a fixed end date (only gas happens to be open-ended) — replaced with the half-open "active right now" test (`valid_from <= NOW() AND (valid_to IS NULL OR valid_to > NOW())`) already used elsewhere in the file. Both fixes applied to Price Curve and Cheapest N-Hour Window together, verified against production.

### What to build

Rewrite the "Cheapest N-Hour Window Today/Tomorrow" query in `grafana/mariadb/queries.md` from a single wide `SELECT` returning 12 paired columns (6 window sizes × start + rate) into a `UNION ALL` of six `SELECT`s — one per window size (30min, 1h, 2h, 3h, 4h, 6h) — each returning `window_size | start | rate`, ordered by window size ascending. Matches the `UNION ALL` style the Price Curve panel already uses in this file. Table panel type unchanged.

### Acceptance criteria

- [x] Query returns exactly one row per window size (6 rows), columns `window_size`, `start`, `rate`.
- [x] Rows are ordered from shortest to longest window.
- [x] Same underlying window-average logic (rolling `AVG(unit_rate)` over the correct row spans) preserved from the original query.
- [x] Executed read-only against production MariaDB and returns 6 rows without error.

---

## Stat-to-Table relabeling (#448)

**Blocked by**: None

**User stories**: 4

### What to build

In `grafana/mariadb/queries.md`, correct the panel-type heading for "Current Billing Period" and "AgilePredict/Kraken Reachability" from "(stat)" to "(table)" — both return three heterogeneous text/date columns rather than a single KPI value, so Grafana's Stat visualization (built for one big number) doesn't fit. No SQL changes.

### Acceptance criteria

- [x] Both panel headings read "(table)" instead of "(stat)"/"(stat/table)".
- [x] SQL for both queries is byte-for-byte unchanged.

---

## Consistency and doc notes (#449)

**Blocked by**: None

**User stories**: 7, 8, 9, 5

### What to build

Four small additive/consistency fixes in `grafana/mariadb/queries.md`:

1. Rename the p/kWh Efficiency vs Day's Avg Rate query's `DATE(...) AS day` column (and its `HAVING`/`ORDER BY` references) to `AS time`, matching the file's existing convention of aliasing genuine time-axis columns `time`.
2. Add a new "Field-formatting convention" callout near the top of the file, alongside the existing "Join convention" and "Local-time convention" notes: cost columns → Grafana currency unit (GBP, £), rate/pence-per-kWh columns → a custom "p/kWh" unit, kWh columns → a custom "kWh" unit, percentage-change columns → Grafana's percent unit.
3. Add a short note under Half-hourly Consumption and Half-hourly Cost recommending bar draw style (not the default line), since each row is a discrete per-interval quantity rather than a continuous signal.
4. Add a short note under the Price Curve panel recommending the `forecast` series be rendered with a dashed line style (and/or muted color) distinct from `actual`, so predicted and confirmed prices are never visually conflated.

### Acceptance criteria

- [x] p/kWh Efficiency query's column and all references renamed `day` → `time`; query still executes and returns correctly ordered rows.
- [x] Field-formatting convention callout present, covering cost/rate(p-per-kWh)/kWh/percent columns, in the same style as existing convention notes.
- [x] Bar-draw-style note present under both half-hourly panels.
- [x] Actual-vs-forecast styling note present under Price Curve.
- [x] p/kWh Efficiency query executed read-only against production MariaDB and returns rows without error.

---

## Billing-period progress gauge (#450)

**Blocked by**: None

**User stories**: 6

### What to build

Merge "This Billing Period's Cost So Far" and "Total Expected Cost This Billing Period" (currently two separate stat panels/queries) into a single panel and query in `grafana/mariadb/queries.md`, returning `actual_cost_to_date` and `projected_total_cost` together from `cost_forecast` in one row, intended for a Grafana Bar Gauge panel (actual as the value, projected as the max/threshold). "Current Billing Period" stays a separate, unchanged Table panel giving the dates for context.

### Acceptance criteria

- [x] Single query returns both `actual_cost_to_date` and `projected_total_cost` from the same (latest `computed_at`) row.
- [x] Panel heading/type updated to reflect a single Bar Gauge panel replacing the two former stat panels.
- [x] "Current Billing Period" panel and query left unchanged.
- [x] Query executed read-only against production MariaDB and returns one row with both values populated.

---

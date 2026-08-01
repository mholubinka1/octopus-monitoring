# Grafana Queries

One SQL block per panel, grouped by dashboard row, meant to be copied directly into Grafana's MySQL/MariaDB query editor. Mirrors the convention used in `pi-desktop/monitoring/grafana/influxdb2/flux_queries` (one query per panel, comment/heading identifying the panel), adapted to Markdown with fenced SQL blocks.

**Status**: reconciled with the current `feature/agile-cost-forecast` and `feature/grafana-dashboard` specs (`.agent-docs/specs/`) — the tariff-comparison feature these queries originally assumed has been dropped entirely; queries below reflect that. Validate against the real schema once implementation lands — table/column names here are the spec input, not yet built (except `consumption`, `agreement`, `product`, `product_rate`, `job_run`, `daily_consumption_summary`, which already exist).

One Grafana dashboard variable is assumed throughout:

- `${region}` — the account's GSP region code (see **Region Code / GSP** in `.agent-docs/context.md`)

## Schema assumed

```text
consumption               (existing) id, energy, period_from, period_to, raw_value, unit, est_kwh
agreement                 (existing) id, energy, product_code, tariff_code, valid_from, valid_to
product                   (existing) product_code PK, display_name, direction
product_rate              (existing) id, product_code, region, valid_from, valid_to, unit_rate, standing_charge
job_run                   (existing) id, job_name, status, ran_at, error_message
daily_consumption_summary (existing) energy, date PK(energy, date), total_kwh
agile_forecast   (new) id, region, period_from, period_to, forecast_unit_rate, fetched_at
cost_forecast    (new) id, billing_period_start, billing_period_end, actual_cost_to_date,
                        projected_total_cost, computed_at
```

`agile_forecast` caches the raw half-hourly AgilePredict response (real 14-day forecast only) for charting. `cost_forecast` is the billing-period-level summary the app computes once daily (actual cost so far + full-period projection, using tiled forecast data internally beyond day 14 — that tiling isn't persisted point-by-point, only the summary is).

**Join convention — half-open windows only.** Any query joining `consumption` to `product_rate` or `agreement` on a `valid_from`/`valid_to` window must use a half-open range: `c.period_from >= valid_from AND c.period_from < COALESCE(valid_to, '9999-12-31 23:59:59')`. Never `BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31 23:59:59')` (inclusive on both ends) — `consumption.period_from` sits on the exact same half-hourly grid as these windows, and adjacent windows are back-to-back (one row's `valid_to` equals the next row's `valid_from`), so an inclusive-both-ends join matches a consumption row against *two* rate rows instead of one, silently doubling every `SUM(est_kwh * unit_rate)` in the query. Confirmed live: before the fix, the Yesterday's Cost panel showed £6.01 — roughly double the £3.19 the corrected query returns for the same day (the official Octopus app showed £3.25 for that day; that residual gap turned out to be a second, distinct bug — see the local-time convention below and issue #434 for the join-doubling investigation).

**Local-time convention — group and label by Europe/London, not raw UTC.** `period_from` is stored as true UTC. Any query that groups or labels by calendar day (`DATE(...)`) or hour-of-day (`HOUR(...)`, `DAYNAME(...)`) must first convert to local time: `CONVERT_TZ(period_from, 'UTC', 'Europe/London')`. During BST this shifts the effective day/hour boundary back by an hour from raw UTC — the difference between a UTC calendar day and the local calendar day Octopus's own app (and a UK user) means by "26 July." Confirmed live: this was the second half of the £3.19-vs-£3.25 residual gap above — the corrected join still bucketed by UTC date, one hour off from the local day boundary. `CONVERT_TZ` requires MariaDB's named-timezone tables to be loaded (confirmed present on the production instance); queries that don't group or label by day/hour (e.g. `Half-hourly Cost`, the `Price Curve`) don't need it, since every timestamp comparison in this file is otherwise a plain UTC-to-UTC instant comparison.

**Field-formatting convention.** Set Grafana's field unit per column, per category, rather than leaving raw numbers unformatted:

- Cost columns already converted to pounds (`cost_gbp`, `*_cost_gbp`) → Grafana's currency (GBP, £) unit.
- Rate columns still in pence/kWh (`rate_pence_per_kwh`, `rate`, `your_avg_rate`, `day_avg_rate`) → a custom unit of `p/kWh` — these are deliberately *not* divided by 100, unlike the cost columns above, so don't apply the GBP unit to them.
- Energy columns (`*_kwh`, `est_kwh`) → a custom unit of `kWh`.
- Percentage-change columns (`yoy_pct_change`, `yoy_pct_change_4wk_avg`) → Grafana's percent unit.

---

## Row 1 — Cost Summary

### Yesterday's Cost (stat, two fields: date + cost)

No dependency on billing period — pure join against data already fully populated by the existing pipeline. `unit_rate`/`standing_charge` are stored in pence/kWh and pence/day respectively (Octopus's own convention, never converted on ingest) — divide by 100 to get GBP.

Not actually always "yesterday" — Octopus's settlement lag means yesterday can still be incomplete, so this searches back up to 7 days for the most recent complete (48-row) day and returns its date alongside its cost, rather than silently mislabeling an older day as "yesterday." If no day within the last 7 days is complete, the panel returns no data.

```sql
WITH daily_costs AS (
  SELECT
    DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London')) AS date,
    ROUND((SUM(c.est_kwh * pr.unit_rate) + MAX(pr.standing_charge)) / 100, 2) AS cost_gbp
  FROM consumption c
  JOIN agreement a
    ON a.energy = c.energy
   AND c.period_from >= a.valid_from
   AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
  JOIN product_rate pr
    ON pr.product_code = a.product_code
   AND pr.region = '${region}'
   AND c.period_from >= pr.valid_from
   AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
  WHERE c.energy = 'E'
    AND c.period_from >= CURDATE() - INTERVAL 7 DAY
    AND c.period_from < CURDATE()
  GROUP BY DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London'))
  -- Completeness guard: see p/kWh Efficiency panel below for the rationale
  -- and why this isn't a fixed 48.
  HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
    CONVERT_TZ(CAST(date AS DATETIME), 'Europe/London', 'UTC'),
    CONVERT_TZ(CAST(date + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
  ) / 30
)
SELECT date, cost_gbp AS yesterday_cost_gbp
FROM daily_costs
ORDER BY date DESC
LIMIT 1;

```

### Billing Period Spend Progress (bar gauge)

Replaces two separate stat panels ("This Billing Period's Cost So Far" and "Total Expected Cost This Billing Period") with a single Bar Gauge: `actual_cost_to_date` as the gauge's value, `projected_total_cost` as its max/threshold, so spend-to-date reads directly as progress toward the full-period projection instead of two disconnected numbers.

```sql
SELECT actual_cost_to_date AS billing_period_cost_gbp, projected_total_cost AS projected_cost_gbp
FROM cost_forecast
ORDER BY computed_at DESC
LIMIT 1;

```

### Current Billing Period (table)

Context for the panel above — shows the dates it's computed against.

```sql
SELECT billing_period_start, billing_period_end, computed_at
FROM cost_forecast
ORDER BY computed_at DESC
LIMIT 1;

```

---

## Row 2 — Electricity

### Price Curve — Today/Tomorrow Actual + Forecast (time series)

`product_rate` has no `period_from` column — for the half-hourly Agile product each row's own `valid_from` *is* the half-hour slot, so that's what stands in for the series' time value here (confirmed against the live schema; `DESCRIBE product_rate` has no `period_from`/`period_to`).

Finds the current agreement via the same half-open test as the **Join convention** above (`valid_from <= NOW() AND NOW() < COALESCE(valid_to, '9999-12-31 23:59:59')`), not `valid_to IS NULL` — Agile agreements are pre-populated with a fixed one-year end date rather than left open-ended, so a `valid_to IS NULL` filter finds no "current" electricity agreement at all once one exists. Confirmed live: production's active electricity agreement (`AGILE-24-10-01`, valid `2026-05-24`–`2027-05-24`) has a set `valid_to`, so the old filter silently returned an empty panel.

Render the `forecast` series with a dashed line (and/or a muted colour) distinct from `actual`'s solid line, so a predicted price is never mistaken for a confirmed one.

```sql
SELECT valid_from AS time, unit_rate AS rate_pence_per_kwh, 'actual' AS series
FROM product_rate
WHERE product_code = (
  SELECT product_code FROM agreement
  WHERE energy = 'E'
    AND valid_from <= NOW()
    AND NOW() < COALESCE(valid_to, '9999-12-31 23:59:59')
  ORDER BY valid_from DESC LIMIT 1
)
AND region = '${region}'
AND valid_from >= CURDATE()

UNION ALL

SELECT period_from AS time, forecast_unit_rate AS rate_pence_per_kwh, 'forecast' AS series
FROM agile_forecast
WHERE region = '${region}'
  AND period_from >= NOW()
ORDER BY time;

```

### Half-hourly Consumption (time series, bar draw style)

Each row is a discrete 30-minute reading, not a continuous signal — use the time series panel's bar draw style rather than the default line, so consecutive intervals aren't visually interpolated into a slope that doesn't exist.

```sql
SELECT period_from AS time, est_kwh
FROM consumption
WHERE energy = 'E'
  AND $__timeFilter(period_from)
ORDER BY period_from;

```

### Half-hourly Cost (time series, bar draw style)

Same reasoning as Half-hourly Consumption above — discrete per-interval values, bar draw style rather than line.

```sql
SELECT
  c.period_from AS time,
  ROUND(c.est_kwh * pr.unit_rate / 100, 4) AS cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from >= a.valid_from
 AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from >= pr.valid_from
 AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND $__timeFilter(c.period_from)
ORDER BY c.period_from;

```

### p/kWh Efficiency vs Day's Avg Rate (time series)

```sql
SELECT
  DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London')) AS time,
  ROUND(SUM(c.est_kwh * pr.unit_rate) / NULLIF(SUM(c.est_kwh), 0), 4) AS your_avg_rate,
  ROUND(AVG(pr.unit_rate), 4) AS day_avg_rate
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from >= a.valid_from
 AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from >= pr.valid_from
 AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND c.period_from >= NOW() - INTERVAL 90 DAY
GROUP BY DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London'))
-- Completeness guard: Octopus's settlement lag means a day can still be
-- missing rows more than 24 hours after it ends -- exclude it rather than
-- show a misleadingly low/high rate computed from a partial day. The
-- expected count is 48 on an ordinary day, but only 46/50 on the UK
-- spring-forward/fall-back dates (a 23- or 25-hour local day) -- computed
-- here rather than hardcoded, since `time` is already the local calendar
-- date after the CONVERT_TZ above.
HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
  CONVERT_TZ(CAST(time AS DATETIME), 'Europe/London', 'UTC'),
  CONVERT_TZ(CAST(time + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
) / 30
ORDER BY time;

```

### Cheapest N-Hour Window Today/Tomorrow (table)

Assumes no gaps in half-hourly `product_rate` rows within the queried range — a missing slot shifts the rolling window incorrectly.

One row per window size (`window_size | start | rate`) rather than one row with 12 paired columns — a single-row table forces horizontal scrolling and pairing columns by eye; this reads top-to-bottom instead. Built as a `UNION ALL` of six single-row `SELECT`s, matching the style the Price Curve panel above already uses. Ordered explicitly via `ORDER BY FIELD(window_size, ...)` rather than relying on `UNION ALL` branch order — every other multi-row panel in this file ends with an explicit `ORDER BY`, and branch order isn't a documented ordering guarantee to lean on.

`product_rate` has no `period_from` column, and the current agreement is found via the same half-open test as the **Join convention** — see the Price Curve panel's notes above for both.

```sql
WITH rates AS (
  SELECT valid_from, unit_rate
  FROM product_rate
  WHERE product_code = (
    SELECT product_code FROM agreement
    WHERE energy = 'E'
      AND valid_from <= NOW()
      AND NOW() < COALESCE(valid_to, '9999-12-31 23:59:59')
    ORDER BY valid_from DESC LIMIT 1
  )
  AND region = '${region}'
  AND valid_from >= CURDATE()
  AND valid_from < CURDATE() + INTERVAL 2 DAY
),
windows AS (
  SELECT
    valid_from AS window_start,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 0  FOLLOWING) AS avg_30min,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 1  FOLLOWING) AS avg_1h,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 3  FOLLOWING) AS avg_2h,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 5  FOLLOWING) AS avg_3h,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 7  FOLLOWING) AS avg_4h,
    AVG(unit_rate) OVER (ORDER BY valid_from ROWS BETWEEN CURRENT ROW AND 11 FOLLOWING) AS avg_6h
  FROM rates
)
(SELECT '30 min'  AS window_size, window_start AS start, avg_30min AS rate FROM windows ORDER BY avg_30min ASC LIMIT 1)
UNION ALL
(SELECT '1 hour'  AS window_size, window_start AS start, avg_1h   AS rate FROM windows ORDER BY avg_1h   ASC LIMIT 1)
UNION ALL
(SELECT '2 hours' AS window_size, window_start AS start, avg_2h   AS rate FROM windows ORDER BY avg_2h   ASC LIMIT 1)
UNION ALL
(SELECT '3 hours' AS window_size, window_start AS start, avg_3h   AS rate FROM windows ORDER BY avg_3h   ASC LIMIT 1)
UNION ALL
(SELECT '4 hours' AS window_size, window_start AS start, avg_4h   AS rate FROM windows ORDER BY avg_4h   ASC LIMIT 1)
UNION ALL
(SELECT '6 hours' AS window_size, window_start AS start, avg_6h   AS rate FROM windows ORDER BY avg_6h   ASC LIMIT 1)
ORDER BY FIELD(window_size, '30 min', '1 hour', '2 hours', '3 hours', '4 hours', '6 hours');

```

### Day-of-Week Average Consumption — Last 12 Weeks (bar chart)

```sql
SELECT
  DAYNAME(d) AS day_of_week,
  ROUND(AVG(daily_kwh), 3) AS avg_kwh
FROM (
  SELECT DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) AS d, SUM(est_kwh) AS daily_kwh
  FROM consumption
  WHERE energy = 'E'
    AND period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London'))
  -- Completeness guard: see p/kWh Efficiency panel above for the rationale.
  HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
    CONVERT_TZ(CAST(d AS DATETIME), 'Europe/London', 'UTC'),
    CONVERT_TZ(CAST(d + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
  ) / 30
) daily
GROUP BY DAYNAME(d)
ORDER BY FIELD(DAYNAME(d), 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday');

```

### Daily Average Usage — 7-Day Rolling Average, 12 Weeks (time series)

```sql
SELECT
  d AS time,
  ROUND(AVG(daily_kwh) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 3) AS rolling_avg_kwh
FROM (
  SELECT DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) AS d, SUM(est_kwh) AS daily_kwh
  FROM consumption
  WHERE energy = 'E'
    AND period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London'))
  -- Completeness guard: see p/kWh Efficiency panel above for the rationale.
  HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
    CONVERT_TZ(CAST(d AS DATETIME), 'Europe/London', 'UTC'),
    CONVERT_TZ(CAST(d + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
  ) / 30
) daily
ORDER BY d;

```

### Daily Average Cost — 7-Day Rolling Average, 12 Weeks (time series)

```sql
SELECT
  d AS time,
  ROUND(AVG(daily_cost) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS rolling_avg_cost_gbp
FROM (
  SELECT
    DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London')) AS d,
    (SUM(c.est_kwh * pr.unit_rate) + MAX(pr.standing_charge)) / 100 AS daily_cost
  FROM consumption c
  JOIN agreement a
    ON a.energy = c.energy
   AND c.period_from >= a.valid_from
   AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
  JOIN product_rate pr
    ON pr.product_code = a.product_code
   AND pr.region = '${region}'
   AND c.period_from >= pr.valid_from
   AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
  WHERE c.energy = 'E'
    AND c.period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London'))
  -- Completeness guard: see p/kWh Efficiency panel above for the rationale.
  HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
    CONVERT_TZ(CAST(d AS DATETIME), 'Europe/London', 'UTC'),
    CONVERT_TZ(CAST(d + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
  ) / 30
) daily
ORDER BY d;

```

### Consumption Heatmap — Hour × Day-of-Week, 45-Day Window (heatmap)

The only panel on the dashboard showing *when in the week* (day and hour together) you use the most electricity — Day-of-Week Average collapses across all 24 hours into one number per day, and none of the time-series panels show a repeating weekly profile at all. Since Agile's cheap/expensive rate windows are also time-of-day and day-of-week correlated, this is the diagnostic view for *where* your usage overlaps with expensive pricing.

Grafana's native Heatmap panel does render this data — the constraint is narrower than "categorical axes aren't supported." With `Calculate from data: Off`, the panel accepts a wide time-series shape: the first time-typed field becomes the X axis, and every other numeric field becomes its own Y-axis row, labelled by that field's column name. So instead of one row per weekday and one column per hour (the shape a Table panel would want), this query is transposed: one row per hour and one column per weekday. `time` is a genuine `DATETIME` — deliberately anchored to *today's* date (`CURDATE()`) purely so the field is time-typed; the date component is discarded visually, only the hour-of-day tick matters, and the panel renders `00:00`–`23:00` ticks natively with zero custom axis formatting as a result. There's no field-mapping UI for any of this in the panel editor — role assignment (which field is X, which are Y-rows) is implicit from the data's shape and typing, not a setting to configure.

`period_from >= NOW() - INTERVAL 45 DAY`, not 90 — `consumption`'s startup backfill only ever pulls `retention_days` (45) of history (see **Retention Window** in `.agent-docs/context.md`), so a 90-day window here would silently return less data than it claims, the same trap the file's other Row 2 panels are separately being fixed for. No completeness-guard `HAVING` clause is needed here, unlike the daily-total panels elsewhere in this file — each cell already averages roughly twelve or fourteen same-weekday-same-hour samples spread over the window (`consumption` is half-hourly, so each hour bucket folds two readings per matching day; a 45-day window gives each weekday roughly six or seven occurrences — 45 ≈ 6×7 + 3 — though `NOW() - INTERVAL 45 DAY` is a rolling cutoff, not calendar-day-aligned, so the exact split shifts by a day depending on where in the week it falls), so one missing half-hour doesn't invalidate a whole cell the way it would invalidate a single day's total. A weekday/hour combination with zero matching rows in the window renders as an empty cell rather than a false zero — deliberate, matching how `AVG(CASE WHEN ...)` already behaves elsewhere in this file.

Set `Calculate from data` to **Off** in the panel editor. Apply the `kWh` custom unit (per the Field-formatting convention above) via a field override with a name-regex matching all seven weekday columns — they don't match the `*_kwh` naming pattern the convention otherwise relies on, so the override needs to name them explicitly. One thing to verify visually once built, not resolvable from Grafana's docs or panel source alone: whether the first value column (`Monday`) renders as the top or bottom row. It should render top — if it comes out reversed, the Heatmap panel's Y-Axis **Reverse** toggle fixes it with no query change.

```sql
SELECT
  TIMESTAMP(CURDATE()) + INTERVAL HOUR(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) HOUR AS time,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Monday'    THEN est_kwh END), 4) AS `Monday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Tuesday'   THEN est_kwh END), 4) AS `Tuesday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Wednesday' THEN est_kwh END), 4) AS `Wednesday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Thursday'  THEN est_kwh END), 4) AS `Thursday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Friday'    THEN est_kwh END), 4) AS `Friday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Saturday'  THEN est_kwh END), 4) AS `Saturday`,
  ROUND(AVG(CASE WHEN DAYNAME(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) = 'Sunday'    THEN est_kwh END), 4) AS `Sunday`
FROM consumption
WHERE energy = 'E'
  AND period_from >= NOW() - INTERVAL 45 DAY
GROUP BY HOUR(CONVERT_TZ(period_from, 'UTC', 'Europe/London'))
ORDER BY time;

```

### Standing Charge vs Unit-Rate Cost Split (stacked bar, daily)

```sql
SELECT
  DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London')) AS time,
  ROUND(SUM(c.est_kwh * pr.unit_rate) / 100, 2) AS unit_rate_cost_gbp,
  ROUND(MAX(pr.standing_charge) / 100, 2) AS standing_charge_cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from >= a.valid_from
 AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from >= pr.valid_from
 AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND $__timeFilter(c.period_from)
GROUP BY DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London'))
-- Completeness guard: see p/kWh Efficiency panel above for the rationale.
HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
  CONVERT_TZ(CAST(time AS DATETIME), 'Europe/London', 'UTC'),
  CONVERT_TZ(CAST(time + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
) / 30
ORDER BY time;

```

---

## Row 3 — Gas

### Gas Consumption (bar)

```sql
SELECT
  DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London')) AS time,
  ROUND(SUM(est_kwh), 3) AS gas_kwh
FROM consumption
WHERE energy = 'G'
  AND $__timeFilter(period_from)
GROUP BY DATE(CONVERT_TZ(period_from, 'UTC', 'Europe/London'))
-- Completeness guard: see p/kWh Efficiency panel above for the rationale.
HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
  CONVERT_TZ(CAST(time AS DATETIME), 'Europe/London', 'UTC'),
  CONVERT_TZ(CAST(time + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
) / 30
ORDER BY time;

```

### Gas Cost (bar)

```sql
SELECT
  DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London')) AS time,
  ROUND((SUM(c.est_kwh * pr.unit_rate) + MAX(pr.standing_charge)) / 100, 2) AS gas_cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from >= a.valid_from
 AND c.period_from < COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from >= pr.valid_from
 AND c.period_from < COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'G'
  AND $__timeFilter(c.period_from)
GROUP BY DATE(CONVERT_TZ(c.period_from, 'UTC', 'Europe/London'))
-- Completeness guard: see p/kWh Efficiency panel above for the rationale.
HAVING COUNT(*) = TIMESTAMPDIFF(MINUTE,
  CONVERT_TZ(CAST(time AS DATETIME), 'Europe/London', 'UTC'),
  CONVERT_TZ(CAST(time + INTERVAL 1 DAY AS DATETIME), 'Europe/London', 'UTC')
) / 30
ORDER BY time;

```

---

## Row 4 — Yearly Comparison

Reads from `daily_consumption_summary`, not raw `consumption` — populated by `feature/yearly-consumption-comparison`'s weekly `update_consumption_summary` job (and a one-time startup backfill), and exempt from the raw-data retention window, so these panels stay correct after `chore/consumption-data-pruning` starts deleting `consumption` rows older than 45 days.

### Monthly Total Consumption — Last 12 Months, Electricity (time series)

Anchored to the first of the month 11 months ago, not `CURDATE() - INTERVAL 12 MONTH` — that would yield a partial *oldest* month instead of 12 full calendar-month buckets. Returns a real `DATE`-typed `time` column rather than a formatted string, so Grafana's native time axis handles tick labels/zoom — matching the convention every other time-series panel in this file uses. Built via `DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY)`, not `DATE_FORMAT(date, '%Y-%m-01')` — `DATE_FORMAT()` always returns a string in MariaDB regardless of the format mask used, even one that looks like a date, so it wouldn't actually fix the original "not a real time axis" defect; date arithmetic on the `DATE`-typed `date` column preserves its type.

```sql
SELECT
  DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY) AS time,
  SUM(total_kwh) AS monthly_kwh
FROM daily_consumption_summary
WHERE energy = 'E'
  AND date >= DATE_FORMAT(CURDATE() - INTERVAL 11 MONTH, '%Y-%m-01')
GROUP BY DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY)
ORDER BY time;

```

### Monthly Total Consumption — Last 12 Months, Gas (time series)

Same real-date `time` convention as the electricity panel above — see its description for the rationale.

```sql
SELECT
  DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY) AS time,
  SUM(total_kwh) AS monthly_kwh
FROM daily_consumption_summary
WHERE energy = 'G'
  AND date >= DATE_FORMAT(CURDATE() - INTERVAL 11 MONTH, '%Y-%m-01')
GROUP BY DATE_SUB(date, INTERVAL DAYOFMONTH(date) - 1 DAY)
ORDER BY time;

```

### Weekly Year-on-Year Change — Last 52/53 Weeks, Electricity (time series)

Groups by `YEARWEEK(date, 3)` (ISO week numbering, mode 3) rather than `YEAR(date)` paired separately with `WEEK(date, 3)` — the latter can misattribute early-January/late-December boundary dates to the wrong week-year, exactly what ISO week numbering exists to avoid. Each week is compared against the same ISO week number one year prior (`yearweek - 100`, e.g. `202630 - 100 = 202530` — subtracting 100 shifts back exactly one week-year while preserving the week number). Both the raw % change and a 4-week trailing moving average of it are returned as separate columns for the same panel.

The panel's displayed x-axis is a real date (`time`, the Monday that ISO week begins on), not the bare `yearweek` integer, so Grafana's time axis works — `yearweek` itself stays internal to the CTEs for the join/arithmetic. Converted via `STR_TO_DATE(CONCAT(yearweek, ' Monday'), '%x%v %W')` — note the **lowercase** `%x%v` (Monday-based ISO week-year), not uppercase `%X%V` (Sunday-based, mode 2): pairing `YEARWEEK(date, 3)` with uppercase specifiers silently round-trips to the wrong date. Confirmed via round-trip (`YEARWEEK(STR_TO_DATE(...), 3) = yearweek`) against production data, including a real week-53 year and a December/January boundary week.

`weekly` only keeps weeks with all 7 days present (`HAVING COUNT(*) = 7`) — the current, still-in-progress ISO week never has 7 days yet, and the oldest weeks near the one-time 2-year backfill's boundary can also be short since that cutoff isn't week-aligned. Filtering incomplete weeks out of `weekly` before `target` and the comparator join both read from it means: an incomplete current week never becomes a target row (nothing sensible to plot for a week that isn't over), and an incomplete comparator week naturally produces a `NULL` `yoy_pct_change` via the `LEFT JOIN` (target week still shown, just no % for that point) instead of dividing against a partial total.

```sql
WITH weekly AS (
  SELECT YEARWEEK(date, 3) AS yearweek, SUM(total_kwh) AS weekly_kwh
  FROM daily_consumption_summary
  WHERE energy = 'E'
  GROUP BY YEARWEEK(date, 3)
  -- Completeness guard: only compare weeks with all 7 days present. The
  -- current, still-in-progress ISO week never has 7 days yet, and the
  -- oldest weeks near the one-time 2-year backfill's boundary can also be
  -- short since that cutoff isn't week-aligned.
  HAVING COUNT(*) = 7
),
target AS (
  SELECT
    yearweek,
    weekly_kwh AS this_year_kwh,
    -- Week-53 fallback: some ISO years have a week 53 (roughly every 5-6
    -- years) but the prior year may only go up to week 52. In that case,
    -- compare against that prior year's week 52 instead of leaving the
    -- comparison null.
    CASE
      WHEN MOD(yearweek, 100) = 53
       AND (yearweek - 100) NOT IN (SELECT yearweek FROM weekly)
      THEN (yearweek - 100) - 1
      ELSE yearweek - 100
    END AS comparator_yearweek
  FROM weekly
  WHERE yearweek >= YEARWEEK(CURDATE() - INTERVAL 52 WEEK, 3)
)
SELECT
  STR_TO_DATE(CONCAT(t.yearweek, ' Monday'), '%x%v %W') AS time,
  ROUND((t.this_year_kwh - c.weekly_kwh) / NULLIF(c.weekly_kwh, 0) * 100, 2) AS yoy_pct_change,
  ROUND(
    AVG((t.this_year_kwh - c.weekly_kwh) / NULLIF(c.weekly_kwh, 0) * 100)
      OVER (ORDER BY t.yearweek ROWS BETWEEN 3 PRECEDING AND CURRENT ROW),
    2
  ) AS yoy_pct_change_4wk_avg
FROM target t
LEFT JOIN weekly c ON c.yearweek = t.comparator_yearweek
ORDER BY t.yearweek;

```

### Weekly Year-on-Year Change — Last 52/53 Weeks, Gas (time series)

Same completeness guard, and same `time` (Monday-of-ISO-week, lowercase `%x%v`) conversion, as the electricity panel above — see its description for the rationale.

```sql
WITH weekly AS (
  SELECT YEARWEEK(date, 3) AS yearweek, SUM(total_kwh) AS weekly_kwh
  FROM daily_consumption_summary
  WHERE energy = 'G'
  GROUP BY YEARWEEK(date, 3)
  -- Completeness guard: see the electricity panel above for the rationale.
  HAVING COUNT(*) = 7
),
target AS (
  SELECT
    yearweek,
    weekly_kwh AS this_year_kwh,
    -- Week-53 fallback: see the electricity panel above for the rationale.
    CASE
      WHEN MOD(yearweek, 100) = 53
       AND (yearweek - 100) NOT IN (SELECT yearweek FROM weekly)
      THEN (yearweek - 100) - 1
      ELSE yearweek - 100
    END AS comparator_yearweek
  FROM weekly
  WHERE yearweek >= YEARWEEK(CURDATE() - INTERVAL 52 WEEK, 3)
)
SELECT
  STR_TO_DATE(CONCAT(t.yearweek, ' Monday'), '%x%v %W') AS time,
  ROUND((t.this_year_kwh - c.weekly_kwh) / NULLIF(c.weekly_kwh, 0) * 100, 2) AS yoy_pct_change,
  ROUND(
    AVG((t.this_year_kwh - c.weekly_kwh) / NULLIF(c.weekly_kwh, 0) * 100)
      OVER (ORDER BY t.yearweek ROWS BETWEEN 3 PRECEDING AND CURRENT ROW),
    2
  ) AS yoy_pct_change_4wk_avg
FROM target t
LEFT JOIN weekly c ON c.yearweek = t.comparator_yearweek
ORDER BY t.yearweek;

```

---

## Row 5 — Health

### Last Successful Run per Job (table)

```sql
SELECT
  job_name,
  MAX(CASE WHEN status = 'success' THEN ran_at END) AS last_success,
  TIMESTAMPDIFF(MINUTE, MAX(CASE WHEN status = 'success' THEN ran_at END), NOW()) AS minutes_since_success
FROM job_run
GROUP BY job_name
ORDER BY job_name;

```

### AgilePredict/Kraken Reachability (table)

Three heterogeneous columns (status, timestamp, error text) in one row — a poor fit for a single-value Stat panel, hence Table.

```sql
SELECT
  status,
  ran_at AS last_checked,
  error_message
FROM job_run
WHERE job_name = 'cost_forecast_refresh'
ORDER BY ran_at DESC
LIMIT 1;

```

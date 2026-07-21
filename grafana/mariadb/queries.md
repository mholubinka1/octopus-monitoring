# Grafana Queries

One SQL block per panel, grouped by dashboard row, meant to be copied directly into Grafana's MySQL/MariaDB query editor. Mirrors the convention used in `pi-desktop/monitoring/grafana/influxdb2/flux_queries` (one query per panel, comment/heading identifying the panel), adapted to Markdown with fenced SQL blocks.

**Status**: reconciled with the current `feature/agile-cost-forecast` and `feature/grafana-dashboard` specs (`.agent-docs/specs/`) — the tariff-comparison feature these queries originally assumed has been dropped entirely; queries below reflect that. Validate against the real schema once implementation lands — table/column names here are the spec input, not yet built (except `consumption`, `agreement`, `product`, `product_rate`, `job_run`, which already exist).

One Grafana dashboard variable is assumed throughout:

- `${region}` — the account's GSP region code (see **Region Code / GSP** in `.agent-docs/context.md`)

## Schema assumed

```text
consumption      (existing) id, energy, period_from, period_to, raw_value, unit, est_kwh
agreement        (existing) id, energy, product_code, tariff_code, valid_from, valid_to
product          (existing) product_code PK, display_name, direction
product_rate     (existing) id, product_code, region, valid_from, valid_to, unit_rate, standing_charge
job_run          (existing) id, job_name, status, ran_at, error_message
agile_forecast   (new) id, region, period_from, period_to, forecast_unit_rate, fetched_at
cost_forecast    (new) id, billing_period_start, billing_period_end, actual_cost_to_date,
                        projected_total_cost, computed_at
```

`agile_forecast` caches the raw half-hourly AgilePredict response (real 14-day forecast only) for charting. `cost_forecast` is the billing-period-level summary the app computes once daily (actual cost so far + full-period projection, using tiled forecast data internally beyond day 14 — that tiling isn't persisted point-by-point, only the summary is).

---

## Row 1 — Cost Summary

### Yesterday's Cost (stat)

No dependency on billing period — pure join against data already fully populated by the existing pipeline.

```sql
SELECT
  ROUND(SUM(c.est_kwh * pr.unit_rate), 2) + MAX(pr.standing_charge) AS yesterday_cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND c.period_from >= CURDATE() - INTERVAL 1 DAY
  AND c.period_from < CURDATE();

```

### This Billing Period's Cost So Far (stat)

```sql
SELECT actual_cost_to_date AS billing_period_cost_gbp
FROM cost_forecast
ORDER BY computed_at DESC
LIMIT 1;

```

### Total Expected Cost This Billing Period (stat)

```sql
SELECT projected_total_cost AS projected_cost_gbp
FROM cost_forecast
ORDER BY computed_at DESC
LIMIT 1;

```

### Current Billing Period (stat/table)

Context for the two panels above — shows the dates they're computed against.

```sql
SELECT billing_period_start, billing_period_end, computed_at
FROM cost_forecast
ORDER BY computed_at DESC
LIMIT 1;

```

---

## Row 2 — Electricity

### Price Curve — Today/Tomorrow Actual + Forecast (time series)

```sql
SELECT period_from AS time, unit_rate AS rate_pence_per_kwh, 'actual' AS series
FROM product_rate
WHERE product_code = (
  SELECT product_code FROM agreement
  WHERE energy = 'E' AND valid_to IS NULL
  ORDER BY valid_from DESC LIMIT 1
)
AND region = '${region}'
AND period_from >= CURDATE()

UNION ALL

SELECT period_from AS time, forecast_unit_rate AS rate_pence_per_kwh, 'forecast' AS series
FROM agile_forecast
WHERE region = '${region}'
  AND period_from >= NOW()
ORDER BY time;

```

### Half-hourly Consumption (time series)

```sql
SELECT period_from AS time, est_kwh
FROM consumption
WHERE energy = 'E'
  AND $__timeFilter(period_from)
ORDER BY period_from;

```

### Half-hourly Cost (time series)

```sql
SELECT
  c.period_from AS time,
  ROUND(c.est_kwh * pr.unit_rate, 4) AS cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND $__timeFilter(c.period_from)
ORDER BY c.period_from;

```

### £/kWh Efficiency vs Day's Avg Rate (time series)

```sql
SELECT
  DATE(c.period_from) AS day,
  ROUND(SUM(c.est_kwh * pr.unit_rate) / NULLIF(SUM(c.est_kwh), 0), 4) AS your_avg_rate,
  ROUND(AVG(pr.unit_rate), 4) AS day_avg_rate
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND c.period_from >= NOW() - INTERVAL 90 DAY
GROUP BY DATE(c.period_from)
ORDER BY day;

```

### Cheapest N-Hour Window Today/Tomorrow (table)

Assumes no gaps in half-hourly `product_rate` rows within the queried range — a missing slot shifts the rolling window incorrectly.

```sql
WITH rates AS (
  SELECT period_from, unit_rate
  FROM product_rate
  WHERE product_code = (
    SELECT product_code FROM agreement
    WHERE energy = 'E' AND valid_to IS NULL
    ORDER BY valid_from DESC LIMIT 1
  )
  AND region = '${region}'
  AND period_from >= CURDATE()
  AND period_from < CURDATE() + INTERVAL 2 DAY
),
windows AS (
  SELECT
    period_from AS window_start,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 0  FOLLOWING) AS avg_30min,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 1  FOLLOWING) AS avg_1h,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 3  FOLLOWING) AS avg_2h,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 5  FOLLOWING) AS avg_3h,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 7  FOLLOWING) AS avg_4h,
    AVG(unit_rate) OVER (ORDER BY period_from ROWS BETWEEN CURRENT ROW AND 11 FOLLOWING) AS avg_6h
  FROM rates
)
SELECT
  (SELECT window_start FROM windows ORDER BY avg_30min ASC LIMIT 1) AS cheapest_30min_start,
  (SELECT MIN(avg_30min) FROM windows)                              AS cheapest_30min_rate,
  (SELECT window_start FROM windows ORDER BY avg_1h ASC LIMIT 1)    AS cheapest_1h_start,
  (SELECT MIN(avg_1h) FROM windows)                                 AS cheapest_1h_rate,
  (SELECT window_start FROM windows ORDER BY avg_2h ASC LIMIT 1)    AS cheapest_2h_start,
  (SELECT MIN(avg_2h) FROM windows)                                 AS cheapest_2h_rate,
  (SELECT window_start FROM windows ORDER BY avg_3h ASC LIMIT 1)    AS cheapest_3h_start,
  (SELECT MIN(avg_3h) FROM windows)                                 AS cheapest_3h_rate,
  (SELECT window_start FROM windows ORDER BY avg_4h ASC LIMIT 1)    AS cheapest_4h_start,
  (SELECT MIN(avg_4h) FROM windows)                                 AS cheapest_4h_rate,
  (SELECT window_start FROM windows ORDER BY avg_6h ASC LIMIT 1)    AS cheapest_6h_start,
  (SELECT MIN(avg_6h) FROM windows)                                 AS cheapest_6h_rate;

```

### Day-of-Week Average Consumption — Last 12 Weeks (bar chart)

```sql
SELECT
  DAYNAME(d) AS day_of_week,
  ROUND(AVG(daily_kwh), 3) AS avg_kwh
FROM (
  SELECT DATE(period_from) AS d, SUM(est_kwh) AS daily_kwh
  FROM consumption
  WHERE energy = 'E'
    AND period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(period_from)
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
  SELECT DATE(period_from) AS d, SUM(est_kwh) AS daily_kwh
  FROM consumption
  WHERE energy = 'E'
    AND period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(period_from)
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
    DATE(c.period_from) AS d,
    SUM(c.est_kwh * pr.unit_rate) + MAX(pr.standing_charge) AS daily_cost
  FROM consumption c
  JOIN agreement a
    ON a.energy = c.energy
   AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
  JOIN product_rate pr
    ON pr.product_code = a.product_code
   AND pr.region = '${region}'
   AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
  WHERE c.energy = 'E'
    AND c.period_from >= NOW() - INTERVAL 84 DAY
  GROUP BY DATE(c.period_from)
) daily
ORDER BY d;

```

### Consumption Heatmap — Hour × Day-of-Week, 90-Day Window (heatmap)

```sql
SELECT
  DAYNAME(period_from) AS day_of_week,
  HOUR(period_from) AS hour_of_day,
  ROUND(AVG(est_kwh), 4) AS avg_kwh
FROM consumption
WHERE energy = 'E'
  AND period_from >= NOW() - INTERVAL 90 DAY
GROUP BY DAYNAME(period_from), HOUR(period_from)
ORDER BY FIELD(DAYNAME(period_from), 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'), hour_of_day;

```

### Standing Charge vs Unit-Rate Cost Split (stacked bar, daily)

```sql
SELECT
  DATE(c.period_from) AS time,
  ROUND(SUM(c.est_kwh * pr.unit_rate), 2) AS unit_rate_cost_gbp,
  ROUND(MAX(pr.standing_charge), 2) AS standing_charge_cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'E'
  AND $__timeFilter(c.period_from)
GROUP BY DATE(c.period_from)
ORDER BY time;

```

---

## Row 3 — Gas

### Gas Consumption (bar)

```sql
SELECT
  DATE(period_from) AS time,
  ROUND(SUM(est_kwh), 3) AS gas_kwh
FROM consumption
WHERE energy = 'G'
  AND $__timeFilter(period_from)
GROUP BY DATE(period_from)
ORDER BY time;

```

### Gas Cost (bar)

```sql
SELECT
  DATE(c.period_from) AS time,
  ROUND(SUM(c.est_kwh * pr.unit_rate) + MAX(pr.standing_charge), 2) AS gas_cost_gbp
FROM consumption c
JOIN agreement a
  ON a.energy = c.energy
 AND c.period_from BETWEEN a.valid_from AND COALESCE(a.valid_to, '9999-12-31 23:59:59')
JOIN product_rate pr
  ON pr.product_code = a.product_code
 AND pr.region = '${region}'
 AND c.period_from BETWEEN pr.valid_from AND COALESCE(pr.valid_to, '9999-12-31 23:59:59')
WHERE c.energy = 'G'
  AND $__timeFilter(c.period_from)
GROUP BY DATE(c.period_from)
ORDER BY time;

```

---

## Row 4 — Health

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

### AgilePredict/Kraken Reachability (stat)

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

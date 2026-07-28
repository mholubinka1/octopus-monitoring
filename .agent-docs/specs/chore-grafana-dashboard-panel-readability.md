# Grafana Dashboard Panel Readability Fixes

## Problem Statement

`grafana/mariadb/queries.md` is the reference doc of one SQL block per panel that will be pasted into Grafana when the dashboard (`feature/grafana-dashboard`) is actually built. A readability review of the file found several panels whose declared chart type doesn't match the shape of data the query returns, which would produce a confusing or broken panel once built: some panels labeled "time series" group by a string or integer rather than a real date, so Grafana's time axis wouldn't work; one panel returns a 12-column single row that's hard to scan as a table; two panels labeled "stat" return multi-column text/date data that doesn't fit Grafana's single-big-number Stat visualization. A broader pass also found an alias inconsistency, a missing unit/format convention that affects almost every panel, no visual distinction between forecast and actual data on the Price Curve, and an opportunity to combine two disconnected stat panels into one panel that shows spend progress at a glance.

## Solution

Fix all eight issues directly in `grafana/mariadb/queries.md`: correct the SQL so panels emit data shaped for their declared chart type, correct panel-type labels where they don't match the data, and add doc-level notes (formatting convention, series styling, draw style) so a future dashboard build produces readable panels without the builder having to rediscover these decisions. Verify each modified/added query by running it read-only against the production MariaDB instance.

## User Stories

1. As the person who will eventually build the Grafana dashboard from this doc, I want the Monthly Total Consumption and Weekly Year-on-Year panels to return a real date column, so that Grafana's native time axis (zoom, pan, tick formatting) works instead of a garbled categorical axis.
2. As the person reading the Weekly Year-on-Year panels, I want each week's date anchored to its Monday, so that the x-axis reads as a normal ISO-week timeline.
3. As the dashboard viewer, I want the Cheapest N-Hour Window panel laid out as one row per window size, so that I can scan start-time/rate pairs without horizontal scrolling.
4. As the dashboard viewer, I want Current Billing Period and AgilePredict/Kraken Reachability correctly labeled as Table panels, so that their multi-column text/date data isn't forced into a big-number Stat visualization it doesn't fit.
5. As the dashboard viewer, I want Half-hourly Consumption and Half-hourly Cost rendered with bar draw style, so that discrete per-interval values aren't visually implied to be a continuous interpolated signal.
6. As the dashboard viewer, I want "This Billing Period's Cost So Far" and "Total Expected Cost This Billing Period" combined into a single Bar Gauge panel, so that I can see spend-to-date against the projection at a glance instead of reading two disconnected numbers.
7. As a future maintainer of this file, I want the p/kWh Efficiency query's date column aliased `time` (matching every other genuine time-series panel in the file), so that the convention is consistent and Grafana's auto-detection of time fields behaves predictably.
8. As a future maintainer of this file, I want a documented field-formatting convention (currency GBP for cost columns, a custom kWh unit for energy columns, percent for YoY change columns), so that panels aren't left showing unformatted raw numbers.
9. As the dashboard viewer, I want the Price Curve panel's "actual" and "forecast" series visually distinguished (e.g. forecast rendered dashed), so that I don't mistake predicted prices for confirmed ones.

## Implementation Decisions

- File touched: `grafana/mariadb/queries.md` only. No schema, application code, or dashboard JSON changes — this doc describes a dashboard that is not yet built (per the file's own status note).
- **Monthly Total Consumption (Electricity + Gas)**: replace the `DATE_FORMAT(date, '%b %Y') AS month` string column with a real date column aliased `time` (first-of-month), dropping the formatted-string column entirely — Grafana formats the axis tick labels from the date itself, matching the convention already used by every other time-series panel in this file (e.g. Half-hourly Consumption, Daily Average Usage).
- **Weekly Year-on-Year Change (Electricity + Gas)**: replace the bare `yearweek` integer column with a real date column aliased `time`, computed as the Monday that ISO week begins on (`STR_TO_DATE(CONCAT(yearweek, ' Monday'), '%X%V %W')` in MariaDB), keeping `yearweek` internally for the joins/CTEs but not as the panel's displayed x-axis field.
- **Cheapest N-Hour Window Today/Tomorrow**: rewrite from a single wide `SELECT` with 12 paired columns into a `UNION ALL` of six `SELECT`s (one per window size — 30min, 1h, 2h, 3h, 4h, 6h), each returning `window_size | start | rate`, ordered by window size ascending. Matches the `UNION ALL` style the Price Curve panel already uses in this file.
- **Current Billing Period** and **AgilePredict/Kraken Reachability**: no SQL changes — only the panel-type heading/label changes from "(stat)" to "(table)", since both return three heterogeneous text/date columns rather than a single KPI value.
- **Half-hourly Consumption** and **Half-hourly Cost**: no SQL changes — add a short note under each specifying the time series panel should use bar draw style rather than the default line, since each row is a discrete per-interval quantity.
- **Billing-period progress gauge**: merge "This Billing Period's Cost So Far" and "Total Expected Cost This Billing Period" into a single panel and query, returning `actual_cost_to_date` and `projected_total_cost` together from `cost_forecast` for use in a Grafana Bar Gauge panel (actual as the value, projected as the max/threshold). Keep "Current Billing Period" as a separate small Table panel giving the dates for context, unchanged.
- **p/kWh Efficiency vs Day's Avg Rate**: rename the `DATE(...) AS day` column (and its `HAVING`/`ORDER BY` references) to `AS time`, for consistency with the rest of the file's convention of aliasing genuine time-axis columns `time`.
- **Field-formatting convention**: add a new callout near the top of the file, alongside the existing "Join convention" and "Local-time convention" notes, documenting: cost columns → Grafana currency unit (GBP, £), kWh columns → a custom "kWh" unit, percentage-change columns → Grafana's percent unit. This is a doc-level note, not a per-query SQL change.
- **Price Curve — actual vs forecast styling**: add a short note under this panel recommending the `forecast` series be rendered with a dashed line style (and/or muted color) distinct from `actual`, so predicted and confirmed data are never visually conflated.

## Testing Decisions

- No automated test suite covers this file — it is copy-paste SQL for Grafana's query editor, not application code.
- Verification seam: execute each new/modified query directly against the production MariaDB instance (`192.168.0.10:3306`, read-only `SELECT`s only, credentials from the repo's `.env`), confirming each runs without error and returns data shaped as described (real date columns parse and sort correctly, the unpivoted window query returns six rows, the merged gauge query returns both figures on one row). This mirrors the verification approach used for the prior timezone/day-bucketing bugfix.
- Unmodified queries (the four "stat"→"table" and bar-draw-style panels, where only labels/notes change) do not need re-execution since their SQL is untouched.

## Out of Scope

- Building the actual Grafana dashboard JSON/provisioning — still tracked separately under `feature/grafana-dashboard`.
- Any change to `agile_forecast`, `cost_forecast`, or other schema/table definitions.
- The three previously-known, unrelated loose threads (empty `product` table, incomplete tariff-type-detection warning, unbuilt dashboard provisioning) — out of scope, untouched.
- Any panel in the file not called out above — the review found no other chart-type/readability defects (all bar/heatmap/stacked-bar/stat/table choices elsewhere were already correct for their data shape).

## Further Notes

Originated from a readability review of `queries.md` conducted earlier in this session (not a user-reported bug). All decisions in this spec were confirmed with the user via a two-axis grill session, including an explicit choice to expand from the 4 originally-flagged issues to a broader pass that surfaced 4 more.

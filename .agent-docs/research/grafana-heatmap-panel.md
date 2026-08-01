# Native Heatmap Panel for the Consumption Heatmap — Research

## TL;DR

Grafana 10.4.2's native Heatmap panel **can** render this data natively, on the
currently-deployed version, with no upgrade and no `Pivot`/`Transpose` transform.
`queries.md`'s current claim — "the Heatmap panel's `Calculate` toggle always expects a
time-typed field on the X axis" — is too strong. The panel has shipped a second,
undocumented-in-the-editor-UI ingestion path since the 9.0 heatmap rewrite: feed it a
**wide time series** (one real time-typed field + several numeric value fields) with
`Calculate: Off`, and it treats **each value field as its own Y-axis row, labelled by
that field's column name** — no `x`/`y`/`xMin`/`yMin` field-name gymnastics, no
categorical-axis support needed. That's exactly the shape `queries.md`'s existing
pivoted Table query already produces, just transposed: instead of one row per weekday
and one column per hour, use one row per hour (a genuine local time value) and one
column per weekday. Source, Grafana's own "What's new in v9.0": *"The new heatmap by
default assumes that the data is pre-bucketed. So if your query returns time series
each series is seen as separate bucket (y axis tick)."*
([whats-new-in-v9-0](https://grafana.com/docs/grafana/latest/whatsnew/whats-new-in-v9-0/))
— this behaviour predates 10.4.2 by five major versions and is untouched by anything
version-gated later.

Recommended: replace the Table workaround with the native Heatmap panel, `Calculate:
Off`, fed by a SQL query transposed from the existing one (hours as rows/time, weekdays
as columns/Y-series) — detailed below. A new pre-materialized table + daily job (same
pattern as `consumption_refresh`) was also weighed (§3c) — it's a valid fallback if the
live query proves too slow, but isn't needed to make the native panel work, so it's not
the primary recommendation.

## 1. What 10.4.2's Heatmap panel actually requires

### 1a. Official docs (10.4-pinned)

[Heatmap — Grafana v10.4 docs](https://grafana.com/docs/grafana/v10.4/panels-visualizations/visualizations/heatmap/)
describes exactly two data-shape-relevant options, both only surfaced when `Calculate
from data` is **On**: `X Bucket` ("This setting determines how the x-axis is split
into buckets") and `Y Bucket` ("...how the y-axis is split into buckets"). When
`Calculate` is **Off**, neither is shown — there is no field-picker, no "Source:
Field" dropdown, no explicit X/Y role-assignment UI anywhere in the panel editor. Role
assignment when `Calculate: Off` is entirely implicit, driven by the shape/typing of
the incoming data frame, not a UI setting. This confirms `queries.md`'s underlying
observation (no field-mapping option exists) but not its conclusion (that the only
accepted shape is time-on-X) — the implicit detection accepts more than one shape.

### 1b. The two implicit shapes, per Grafana's own dataplane contract

[Heatmap — Grafana Data Structure](https://grafana.com/developers/dataplane/heatmap)
(the schema Grafana's own docs point to for exactly this question) documents two
frame types the panel's `Calculate: Off` path accepts:

- **`HeatmapCells`** (long/sparse format) — "each row in the frame indicates the value
  of a single cell in a heatmap," with field roles found by name:
  `x`/`xMin`/`xMax` and `y`/`yMin`/`yMax`. This is the shape `queries.md`'s prose was
  implicitly reasoning about (and rightly rejected — see 1c).
- **`HeatmapRows`** (wide format) — *"The first field represents the X axis, the rest
  of the fields indicate rows in the heatmap."* Equivalently: *"Timeseries wide can be
  used directly as heatmap-rows, in this case each value field becomes a row in the
  heatmap."* This is the shape this recommendation uses.

Confirmed present well before 10.4.2 (not a recent addition): [What's new in Grafana
v9.0](https://grafana.com/docs/grafana/latest/whatsnew/whats-new-in-v9-0/) — *"The new
heatmap by default assumes that the data is pre-bucketed. So if your query returns
time series each series is seen as separate bucket (y axis tick)."* The "new heatmap"
referenced there is the same panel implementation still in use in 10.4.2 (confirmed by
reading the panel source at the `v10.4.2` tag — see 1c) and in every version since.

### 1c. Verified against the 10.4.2 panel source (github.com/grafana/grafana, tag `v10.4.2`)

- `public/app/plugins/panel/heatmap/fields.ts` — the `HeatmapCells` (sparse) path
  identifies X/Y fields by an exact `switch` on field **name** (`'x' | 'xMin' |
  'xMax'` and `'y' | 'yMin' | 'yMax'`), not by Grafana `FieldType`. There is no type
  check forcing the X field to be `time` in this code path — a field literally named
  `x` of any type is accepted structurally. This is one concrete way `queries.md`'s
  "always expects a time-typed field" claim overstates the constraint, though this
  sparse-cells path still isn't the one this recommendation uses (see "alternatives
  considered" below for why).
- `public/app/plugins/panel/heatmap/utils.ts`, function `prepConfig` (verified: this
  is a function inside `utils.ts`, not its own file — corrected from an earlier draft
  of this note) — the rendering/axis-config code contains an explicit fallback branch
  for a non-time first field: `if (dataRef.current?.heatmap?.fields[0].type !==
  FieldType.time) { xScaleUnit = ...config?.unit ?? 'x'; isTime = false; }`. The
  existence of this branch is further evidence the panel does not hard-require
  `FieldType.time` on X to avoid erroring — it degrades gracefully to a generic linear
  axis instead (uPlot still needs the values to be numeric, not string, for this
  fallback to render sensibly). (Not the approach used below, which keeps X genuinely
  time-typed for better tick rendering — but it shows the "always" in `queries.md`'s
  current prose is not accurate to the source.)

### 1d. The fixed-reference-week / fake-time-axis pattern (question asked to verify)

Verified as viable but **not needed** here. A `y=HOUR` (0-23, numeric field, no
special name required) with `x=` a real calendar timestamp works fine as an
`HeatmapCells`-shaped input (per 1c, field-name matching, no type gate) — but it's
strictly more SQL/config complexity than the wide-format (`HeatmapRows`) approach,
which needs no `x`/`y`-named columns at all, just a time-typed first column and
ordinary named value columns. Recommendation below uses the simpler shape.

## 2. Recommended approach

**Panel**: native Heatmap, `Calculate from data`: **Off**. No transform of any kind
(no `Pivot`, no `Transpose`) — the SQL query itself already returns the final
wide-row shape, exactly as the existing Table panel's query already does today, just
transposed.

**Field roles** (implicit, per 1b — no panel-editor field mapping exists to set):
first field (`time`, real `DATETIME`) → X axis; each of the seven weekday columns → one
Y-axis row, labelled by its column name (`Monday`, `Tuesday`, ... `Sunday`); cell
colour → that column's value for the row's hour.

**Field-formatting convention** (per `queries.md`'s existing convention section):
apply the `kWh` custom unit to the seven weekday value fields (matches the `*_kwh`
category), via a field override with a name-regex covering all seven, same mechanism
the Table version presumably already uses for its 24 hour-columns.

**SQL** — the transpose of the existing panel's query. Same `WHERE`/window/local-time
conventions (45-day cap per the file's retention note, `CONVERT_TZ` for local-day/hour
labelling, no completeness-guard `HAVING` — this panel doesn't need one, same as
today's version, since each cell already averages across twelve or fourteen
same-weekday-same-hour samples (`consumption` is half-hourly, and 45 days gives each
weekday six or seven occurrences) spread over the window rather than summing one
calendar day, so a single
missing half-hour doesn't invalidate a whole day's bucket the way the daily-total
panels' guard protects against):

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

Notes on this query:

- `time` is a genuine `DATETIME`, deliberately anchored to *today's* date
  (`CURDATE()`) purely so the field is `FieldType.time` — the date component is
  discarded visually (only the hour-of-day tick matters, and the panel renders
  `00:00`–`23:00` ticks naturally with zero custom axis formatting, since it's a real
  time field). No `${region}` variable — this panel, like the current Table version
  and the Day-of-Week Average panel above it, only reads `consumption`, never joins to
  `product_rate`/`agreement`.
- Column order (`Monday` → `Sunday`) is the Y-row order the panel will render, per the
  v9.0-documented "each series is seen as a separate bucket (y axis tick)" behaviour —
  same ordering mechanism `queries.md`'s other weekday panels already use via `ORDER
  BY FIELD(...)`, just expressed as column order instead of row order here.
- One thing to verify visually once built, not resolvable from docs/source alone:
  whether the panel plots the first value column (`Monday`) at the top or bottom row —
  10.4.2's Heatmap panel has a `Reverse` toggle under Y-Axis options if the initial
  render comes out upside-down relative to intent.

## 3. Alternatives considered

**3a. `HeatmapCells` sparse shape with a fixed-reference-week fake time axis** (one row
per weekday×hour, `x`-named real timestamp, `y`-named numeric hour, `value`-named
kWh). Verified viable per §1c/1d — field-name matching doesn't require `FieldType.time`
on X — but it's strictly worse than 3-2 here: it needs exact reserved field names
(`x`/`y`/`value`, more fragile to get an SQL alias wrong against undocumented-in-the-
UI conventions) where the wide-format approach needs no special names at all, just
ordinary weekday column headers. No reason to prefer it for this panel.

**3b. Upgrade Grafana and use the `Pivot`/`Transpose` transform.** `queries.md`
currently says this "doesn't exist until Grafana 11.x" — confirmed directionally
correct but the transform's actual name is **`Transpose`**, not `Pivot`, and it landed
specifically in **v11.2** (not 11.0): [What's new in
v11.2](https://grafana.com/docs/grafana/latest/whatsnew/whats-new-in-v11-2/) and the
[Grafana 11.2 release blog](https://grafana.com/blog/2024/08/28/grafana-11.2-release-all-the-new-features/)
both describe it as community-contributed, GA at launch across all editions, and
functionally exactly "pivot the data frame, converting rows into columns and columns
into rows." This is a real path (it would let the *existing* long-format
`day_of_week, hour_of_day, avg_kwh` query feed the Heatmap panel with a transform doing
the reshaping instead of `CASE WHEN` pivoting in SQL) but requires a version jump of
several majors (10.4.2 → 11.2+) — not evaluated here for other-panel breaking changes
beyond a skim of the 11.2 release notes, which didn't surface anything heatmap- or
this-project-relevant beyond the Transpose transform itself. Not recommended as the
fix for this panel specifically, since §2 already achieves the goal with zero version
risk; worth keeping in mind only if a future panel genuinely needs a general-purpose
pivot Grafana-side rather than in SQL.

**3c. A new pre-materialized table + daily job**, populated on the same schedule
pattern as the existing `consumption_refresh`/`cost_forecast_refresh` jobs (rows in
`job_run`). Verified as structurally compatible with §2's recommended shape: the job
would compute the same `AVG(est_kwh)` grouped by `(day_of_week, hour_of_day)` over the
45-day window — still collapsing to 7×24=168 cells, not raw per-day rows — and write
one row per cell (or one row per hour with 7 weekday columns, mirroring §2's SQL
shape) into a new table, e.g. `consumption_heatmap_summary(hour_of_day, monday_kwh,
tuesday_kwh, ..., sunday_kwh, computed_at)`. The Grafana panel query then becomes a
trivial `SELECT * FROM consumption_heatmap_summary ORDER BY hour_of_day` — same field
roles and Heatmap config as §2, just reading a pre-computed table instead of
aggregating `consumption` live. **Tradeoff vs the live query in §2**: staleness (data
is only as fresh as the last daily job run, whereas §2's live query recomputes on every
dashboard load/refresh) traded for a cheaper panel query (no `GROUP BY`/`CASE WHEN`
scan of up to 45 days × 48 half-hourly rows on every dashboard open) and a job-run
health signal for free (shows up in the existing "Last Successful Run per Job" panel).
Given this query's cost is modest — it's a single-table scan with no join, unlike the
`product_rate`-joined panels this file's performance note (line 29 above) warns about —
the live-query approach in §2 is recommended first; the materialized-table path is a
legitimate fallback if the live query proves too slow in practice against production
data volumes, or if a future feature wants to trend this weekly profile over time
(which a daily-refreshed table would support and a live-only query would not, since
each day's aggregate wouldn't be retained).

**3d. Non-Heatmap panel plugins** (secondary, one paragraph per the research brief).
[marcusolsson-hourly-heatmap-panel](https://grafana.com/grafana/plugins/marcusolsson-hourly-heatmap-panel/)
is compatible back to Grafana 8.0 (fine on 10.4.2) but its README describes it as
plotting **actual calendar dates** on one axis and hour-of-day on the other — a
date × hour-of-day calendar heatmap, not a weekday × hour-of-day weekly profile — its
own maintainer discussion thread
([#57](https://github.com/marcusolsson/grafana-hourly-heatmap-panel/discussions/57))
shows day-of-week-on-an-axis was requested and not resolved, so it doesn't solve this
panel's actual shape any better than the native panel does, and adds a third-party
plugin dependency for no gain. Volkov Labs' Business/ECharts panel (`volkovlabs-echarts-panel`,
listed on its plugin page as "Business Charts") — raised as a "greater customization"
suggestion in one community thread — the current release (7.2.5) requires
**Grafana >= 12.3.0** per its [plugin page](https://grafana.com/grafana/plugins/volkovlabs-echarts-panel/);
its compatibility table shows the older 6.x line supported Grafana 10/11, so it isn't
categorically impossible on 10.4.2 if pinned to an old, unsupported plugin version —
but that trades a stale, unmaintained third-party plugin for a solved problem (§2
already works with zero plugin dependency), so it's not worth it here. Neither
alternative is a better fit than §2.

## 4. Community precedent (context, not the basis for the recommendation)

Two Grafana community forum threads independently arrived at the same Table-panel
workaround `queries.md` already documents, for the same day-of-week × hour-of-day
shape, on older versions — useful as corroboration that the native panel's
categorical-axis gap is a long-standing, widely-hit limitation, not specific to this
project's data:
[Aggregated heatmap of user activity by 24h buckets / day of week](https://community.grafana.com/t/aggregated-heatmap-of-user-activity-by-24h-buckets-on-y-axis-and-the-day-of-the-week-on-x-axis/83325)
(Grafana 9.4.1, unresolved in-thread) and
[HeatMap by Day's and hours (not date)](https://community.grafana.com/t/heatmap-by-days-and-hours-not-date/100509)
(Grafana 9.5.1, resolved with "a regular 'table panel' in the end with some styling for
the cells" — the same pattern `queries.md` uses today). Neither thread mentions the
wide-time-series `HeatmapRows` path from §1b/§2 — it appears to be a
genuinely under-documented-in-community capability, only found by reading Grafana's
own dataplane contract page and the v9.0 release notes directly, not something people
organically rediscover on the forums.

## 5. Distinction flagged, and explicitly ruled out (per research brief §1's third sub-option, and confirmed out of scope by the user directly)

A **45-day calendar heatmap** (X = actual date, Y = hour-of-day, no weekday
collapsing, ~1,080 raw cells for 45 days × 24 hours with no aggregation) was
investigated as a structurally simpler option — it would fit `HeatmapCells` naturally
(`x` = real `DATE(CONVERT_TZ(...))`, `y` = numeric hour, `value` = kWh, one row per
actual date+hour) and need no weekday `CASE WHEN` pivoting at all. **This is
explicitly ruled out**, not just deprioritized: the panel's required shape is a fixed
7 (day-of-week) × 24 (hour-of-day) = 168-cell grid, with each cell averaged across
every occurrence of that weekday/hour pair over the full 45-day window — a weekly
consumption *profile*, matching what `queries.md` already describes as this panel's
purpose ("the only one on the dashboard showing *when in the week* ... a repeating
weekly profile") and confirmed directly, not inferred. Recommendation §2's query
already produces exactly this 168-cell aggregate (`GROUP BY HOUR(...)` × 7
`AVG(CASE WHEN DAYNAME(...) = ...)` columns, one value per weekday/hour pair, never
one row per raw calendar day) — same aggregation shape a materialized-table version
(§3c) would also need to preserve, not raw per-day granularity. This section exists
only so a future reader doesn't rediscover the calendar-heatmap idea and assume it was
overlooked rather than deliberately rejected.

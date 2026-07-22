# Weekly YoY Panel: Exclude Incomplete Weeks

## Problem Statement

The Weekly Year-on-Year Change panels (`grafana/mariadb/queries.md`, Row 4 —
Yearly Comparison) treat every `YEARWEEK(date, 3)` bucket in
`daily_consumption_summary` as a full 7-day week, with no check that it
actually is. Two situations currently produce misleading numbers:

1. **The current, still-in-progress ISO week** is always included as the
   most recent target row. `daily_consumption_summary` is refreshed on every
   app startup and every Monday (`ConsumptionSummaryRetriever.refresh`),
   which recomputes a trailing 14-day window including today — so "today"
   carries whatever partial/lagged consumption exists, not a full day's
   total. That partial day rolls into the current week's `SUM(total_kwh)`,
   which then gets compared against a *complete* week from a year earlier.
   The result is an artificial YoY dip on the most recent point, and because
   the 4-week moving average trails over `t.yearweek`, the dip also drags
   down the last several points of the smoothed series.
2. **The oldest comparator week**, at the edge of the one-time 2-year
   backfill (`ConsumptionSummaryBackfill`, `BACKFILL_WINDOW_DAYS = 730`), can
   also be partial. The backfill cutoff is a fixed day-count anchored to
   midnight UTC, not aligned to an ISO week boundary, so the earliest date in
   `daily_consumption_summary` lands mid-week. The 52-week chart's oldest
   target row is ISO-week ~52 weeks ago; its comparator (`yearweek - 100`) is
   ~104 weeks ago — right at that 730-day boundary. The left edge of the
   chart can end up comparing against an artificially low (partial)
   denominator.

Both are the same root cause: nothing filters out weeks with fewer than 7
summarized days, on either the target or comparator side.

## Solution

Only compare ISO weeks that have a full 7 days of summarized data in
`daily_consumption_summary`, on both the target and comparator side. A week
lacking any day's summary (whether because it hasn't finished yet, because
it falls just outside the 2-year backfill's boundary, or because of any
future data gap — meter downtime, a missed job run) is treated as
incomplete and excluded, using the same mechanism regardless of cause.

- If the **target** week is incomplete, it does not appear as a data point
  in the chart at all — there is nothing sensible to plot for a week whose
  own total isn't final.
- If the target week is complete but its **comparator** week is incomplete,
  the target week still appears on the x-axis, but `yoy_pct_change` and the
  4-week moving average are `NULL` for that point — the same pattern
  already used for the week-53 fallback when no comparator exists at all.

## User Stories

1. As the account holder, I want the most recent point on the Weekly YoY
   chart to reflect a fully-finished week, so that I don't see a misleading
   artificial dip every time I open the dashboard mid-week.
2. As the account holder, I want the 4-week moving average to only be
   computed over complete weeks, so that a partial current week doesn't
   drag down the trend line for several weeks running.
3. As the account holder, I want the oldest points on the chart (near the
   2-year backfill boundary) to not show a distorted comparison caused by a
   partial historical week, so that the chart doesn't need special
   knowledge of when the backfill happened to be trusted.

## Implementation Decisions

- **Modules changed**: `grafana/mariadb/queries.md` only (Row 4 — Yearly
  Comparison, "Weekly Year-on-Year Change" panels for electricity and gas).
  No application code changes — this is a query-only fix, consistent with
  how the panels originally shipped.
- **Mechanism**: add `HAVING COUNT(*) = 7` to the `weekly` CTE in both the
  electricity and gas queries. `daily_consumption_summary` has a true
  composite `(energy, date)` primary key (ADR-0008), and `weekly` is already
  filtered to a single energy before grouping by `YEARWEEK(date, 3)`, so
  `COUNT(*)` after that `GROUP BY` is exactly "number of distinct days
  present in this ISO week" — no `DISTINCT` needed.
- **Why one change covers both bugs**: `target` is built `FROM weekly`, so
  an incomplete current week is automatically excluded from ever being a
  target row. The comparator join (`LEFT JOIN weekly c ON c.yearweek =
  t.comparator_yearweek`) automatically yields `NULL` for `c.weekly_kwh`
  when the comparator week was filtered out of `weekly` for being
  incomplete — which combined with `NULLIF(c.weekly_kwh, 0)` already
  produces `NULL` for `yoy_pct_change`, satisfying the "point still shown,
  null %" behavior without further changes.
- **Interaction with the existing week-53 fallback**: unaffected. The
  fallback's `(yearweek - 100) NOT IN (SELECT yearweek FROM weekly)` check
  now also correctly treats an incomplete week 53 as "doesn't exist" and
  falls back to week 52, which is the desired behavior.
- **Inline SQL comment**: add a short comment next to the new `HAVING`
  clause explaining the rationale (in-progress week + backfill-boundary
  week both being reasons a week can be short), matching the existing
  inline-comment convention used for the week-53 fallback in this file.
- **Glossary update**: extend the `Yearly Comparison` entry in
  `.agent-docs/context.md` to mention that only complete (7-day) ISO weeks
  are compared, and why.

## Testing Decisions

- **No automated test.** `YEARWEEK` and the window-function moving average
  are MariaDB-specific and not supported by the SQLite in-memory fixtures
  used elsewhere in this repo's test suite (e.g.
  `test_agreement_persistence.py`). The original two Yearly Comparison
  panels shipped the same way — documentation-only, validated by reasoning
  through the SQL rather than an automated test.
- **Validation approach**: reason through the SQL against representative
  cases (a fully up-to-date table, a table with a partial current week, a
  table with a partial oldest week near a 730-day-ago cutoff, and the
  week-53-fallback case) and, if a real or test MariaDB instance is
  reachable, run the query against it manually before merging.

## Out of Scope

- The Monthly Total Consumption panel has an analogous partial-current-month
  issue (the current month's bar is short because the month isn't over
  yet), but it's a less severe bug — a short bar, not a misleading
  percentage swing — and is not part of this fix.
- No change to `ConsumptionSummaryBackfill`, `ConsumptionSummaryRetriever`,
  or the `BACKFILL_WINDOW_DAYS` constant. The fix is entirely on the query
  side; the underlying data-population code is unchanged.
- No change to the 52-week window size (still `yearweek >= YEARWEEK(CURDATE()
  - INTERVAL 52 WEEK, 3)`) — excluding the current incomplete week simply
  means the chart's rightmost point is the most recent *complete* week,
  narrowing the effective display to ~51-52 complete weeks rather than
  widening the lower bound to compensate.

## Further Notes

Investigated and agreed via `/design` session prior to this spec. Both
issues were confirmed by reading `ConsumptionSummaryRetriever.refresh`
(`app/data/consumption_summary.py`), `read_consumption_summarization_window`
(`app/data/mysql/client.py`), and `ConsumptionSummaryBackfill.run`
(`app/data/consumption_summary.py`) alongside the existing query in
`grafana/mariadb/queries.md`.

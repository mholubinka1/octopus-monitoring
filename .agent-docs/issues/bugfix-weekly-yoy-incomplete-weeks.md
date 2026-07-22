# Issues: bugfix-weekly-yoy-incomplete-weeks

## Exclude incomplete ISO weeks from Weekly YoY panels (#418)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Add a `HAVING COUNT(*) = 7` guard to the `weekly` CTE in both the
electricity and gas "Weekly Year-on-Year Change" queries in
`grafana/mariadb/queries.md` (Row 4 — Yearly Comparison). Since
`daily_consumption_summary` has a composite `(energy, date)` primary key and
`weekly` is already filtered to a single energy before grouping by
`YEARWEEK(date, 3)`, `COUNT(*) = 7` after that `GROUP BY` means exactly "all
7 days of this ISO week are present."

This single change removes incomplete weeks from `weekly` before either the
`target` or comparator side reads from it, so:

- An incomplete current (still in-progress) week never appears as a target
  row — no partial-week data point on the chart.
- An incomplete week near the 2-year backfill boundary never gets used as a
  comparator — the `LEFT JOIN weekly c` naturally yields `NULL`, so
  `yoy_pct_change` and the 4-week average are `NULL` for that point (target
  week still shown on the x-axis) rather than computed against a partial
  denominator.
- The existing week-53 fallback (`(yearweek - 100) NOT IN (SELECT yearweek
  FROM weekly)`) is unaffected — it already checks against `weekly`, so an
  incomplete week 53 correctly falls back to week 52.

Add an inline SQL comment next to the new `HAVING` clause explaining why a
week can be short (in-progress week or backfill-boundary week), matching
the existing comment style used for the week-53 fallback. Update the
`Yearly Comparison` entry in `.agent-docs/context.md` to mention the
completeness guard. Documentation-only — no application code changes.

### Acceptance criteria

- [ ] `HAVING COUNT(*) = 7` (or equivalent) added to the `weekly` CTE in
      both the electricity and gas Weekly YoY queries in
      `grafana/mariadb/queries.md`
- [ ] An inline comment explains why the guard exists (in-progress current
      week + partial backfill-boundary week), consistent with the file's
      existing comment conventions
- [ ] The week-53 fallback logic still correctly falls back to week 52 when
      week 53 is either missing entirely or present-but-incomplete
- [ ] No application code changes — `app/` is untouched
- [ ] `.agent-docs/context.md`'s `Yearly Comparison` entry mentions that
      only complete (7-day) ISO weeks are compared, and why
- [ ] Manually reasoned through against: an up-to-date table, a partial
      current week, a partial oldest week near the 730-day backfill cutoff,
      and the week-53-fallback case — and run against a real/test MariaDB
      instance if one is reachable

---

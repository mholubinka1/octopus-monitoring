# Issues: feature-yearly-consumption-comparison

## Daily consumption summary schema (#401)

**Blocked by**: None

**User stories**: 1, 2, 4, 5 (foundational)

### What to build

Add the new `daily_consumption_summary` table to `app/data/mysql/model.py`
(composite primary key `energy, date`, plus `total_kwh`) — picked up
automatically by the existing additive schema sync, no `init.sql` change
needed. Add `MariaDBClient.write_consumption_summary`, following the existing
`write_agreement`/`write_product_rate` upsert pattern. No retrieval/job logic
in this slice — it only lands the schema and the write path so the next slice
can populate it.

### Acceptance criteria

- [ ] `daily_consumption_summary(energy, date, total_kwh)` exists in
      `model.py` with `(energy, date)` as the composite primary key
- [ ] `MariaDBClient.write_consumption_summary` upserts rows via the existing
      `upsert`/`session_write_scope` pattern
- [ ] A unit test (SQLite in-memory, mirroring `test_agreement_persistence.py`)
      asserts upsert-on-conflict behaviour for the new table
- [ ] Existing test suite remains green

---

## Populate daily_consumption_summary from raw consumption (#402)

**Blocked by**: #401

**User stories**: 1, 2, 4, 5

### What to build

New module `app/data/consumption_summary.py` with a
`ConsumptionSummaryRetriever` (mirroring `ConsumptionRetriever`/
`PricingRetriever`'s shape). Its `refresh()` determines the summarization
window — the trailing 14 days, plus any date with raw `consumption` rows but
no existing summary row — sums `est_kwh` grouped by `DATE(period_from)` and
`energy` for that window, and upserts each `(energy, date)` total via
`write_consumption_summary`. Re-summarizing the trailing 14 days on every run
(not just never-summarized days) is what absorbs upstream Octopus
consumption corrections.

### Acceptance criteria

- [ ] Given seeded `consumption` rows across several days for both energies,
      running `refresh()` produces correct `daily_consumption_summary` totals
      per `(energy, date)`
- [ ] Given a day's summary row already exists with a stale total, and raw
      `consumption` for that day (within the trailing 14 days) now sums to a
      different total, running `refresh()` again corrects the stored total
- [ ] Given raw `consumption` exists for a day older than 14 days with no
      existing summary row, running `refresh()` summarizes that day too (gap
      case)
- [ ] Existing test suite remains green

---

## Schedule the weekly consumption-summary job (#403)

**Blocked by**: #402

**User stories**: 1, 2, 4, 5

### What to build

Register `ConsumptionSummaryRetriever.refresh()` as a new scheduled job,
`update_consumption_summary`, on a fixed weekly cadence — Monday at 03:00
(`scheduler.every().monday.at("03:00")`) — distinct from the existing
`refresh_interval_hours`-driven consumption/pricing jobs. Wrap it in the
existing `job_run` mechanism, reusing `_schedule_refresh_job`'s
background-worker-thread-with-backoff mechanism
(`bugfix/consumption-timezone-and-scheduler-backoff`, not the plain
try/except this issue originally assumed) so its outcome is recorded like
every other scheduled job and a persistently-failing run backs off instead
of retrying every tick. Generalize `_schedule_refresh_job` to take the
scheduling interval as a `Callable[[Scheduler], Job]` instead of hardcoding
`.hours`, so both the existing hourly-ish jobs and this weekly one share the
same wrapper with no duplication. Introduce a `WEEKLY_JOB_TIME = "03:00"`
constant, plus a forward-looking (currently unused) `DAILY_JOB_TIME = "04:00"`
constant for future daily-cadence jobs. This is also the job
`chore/consumption-data-pruning`'s pruning job will be gated on succeeding.

### Acceptance criteria

- [ ] `update_consumption_summary` is registered on `scheduler.every().monday.at("03:00")`,
      independent of `refresh_interval_hours`
- [ ] A successful run records a `job_run` row with `status="success"`
- [ ] A failing run records `status="failure"` with the error message, and
      does not crash the app (matches `test_refresh_scheduling.py`'s existing
      pattern for the other scheduled jobs)
- [ ] `_schedule_refresh_job` is generalized (interval as a callback) with
      no behavioural change to the existing hourly consumption/pricing jobs
- [ ] Existing test suite remains green

---

## One-time 2-year historical backfill for daily_consumption_summary (#415)

**Blocked by**: #402

**User stories**: 1, 2, 3, 4, 5

### What to build

A new `ConsumptionSummaryBackfill` class (`app/data/consumption_summary.py`,
alongside `ConsumptionSummaryRetriever`), following the same verb-Protocol DI
seam as `ConsumptionRetriever`/`PricingRetriever` — this one calls the
external Octopus API directly, unlike #402's pure DB-to-DB retriever. On
first startup only, it fetches ~2 years of consumption per meter via the
existing paginated `fetch_consumption`/`fetch_consumption_page` verbs,
aggregates in memory by `(energy, date)`, and writes only to
`daily_consumption_summary` via a new `persist_consumption_summary` verb —
never to raw `consumption`, so the 45-day retention window is unaffected.

Idempotency is gated on `job_run` history: a new
`MariaDBClient.has_successful_job_run(job_name)` checks whether a `job_run`
row with `status="success"` already exists for job name
`yearly_comparison_backfill`; if so, the backfill no-ops. Runs once at
startup (not on the recurring scheduler), in a background thread reusing the
same retry-with-backoff mechanism as `_schedule_refresh_job`.

Also reverts `config.yml`/`config.yml.template`'s `retention_days` from
`400` to `45` (and the README's Configuration section) — the dedicated
2-year backfill makes the earlier rationale for the elevated value obsolete.
GitHub issue #406 (on `chore/consumption-data-pruning`) already tracks this
same revert; once this ships, #406 will find it already done.

### Acceptance criteria

- [ ] `ConsumptionSummaryBackfill.run()` fetches ~2 years of consumption per
      meter and writes correct `daily_consumption_summary` totals per
      `(energy, date)`, without writing any rows to raw `consumption`
- [ ] A second call (simulating an app restart) is a no-op — no further
      Octopus API calls, verified via the `job_run` gate
- [ ] A persistently-failing backfill retries with exponential backoff
      (mirroring `test_refresh_scheduling.py`'s existing pattern) and does
      not crash startup
- [ ] `config.yml`/`config.yml.template`'s `retention_days` is `45`;
      README's Configuration section updated to match
- [ ] Existing test suite remains green

---

## Grafana panel: monthly total consumption, last 12 months (#404)

**Blocked by**: #401

**User stories**: 1, 4

### What to build

Add a new panel definition to `grafana/mariadb/queries.md`: monthly total
consumption over the trailing 12 months, one series per energy
(electricity/gas), x-axis labelled "Mon YYYY" (e.g. "Jan 2026") via
`DATE_FORMAT(date, '%b %Y')`, grouped by calendar month against
`daily_consumption_summary`. Documentation-only change — no application code.

### Acceptance criteria

- [ ] Query added to `grafana/mariadb/queries.md` under a new "Yearly
      Comparison" section, following the existing one-query-per-panel,
      fenced-SQL convention
- [ ] Query groups by calendar month, covers the trailing 12 months, and
      produces a distinct row per energy
- [ ] The window is 12 full calendar-month buckets (current month plus the
      11 preceding complete months) — anchored to the first of the month,
      not a naive `CURDATE() - INTERVAL 12 MONTH`, which yields a partial
      *oldest* month instead
- [ ] Month label format is `%b %Y` (e.g. "Jan 2026"), not month name alone

---

## Grafana panel: weekly year-on-year change, last 52/53 weeks (#405)

**Blocked by**: #401

**User stories**: 2, 3, 4

### What to build

Add a second new panel definition to `grafana/mariadb/queries.md`: for
each of the last 52/53 ISO weeks, the % change in total consumption versus
the same ISO week number one year prior, plus a 4-week trailing moving
average of that % change as a second series — one panel per energy. Group
by `YEARWEEK(date, 3)` — not `YEAR(date)` paired separately with
`WEEK(date, 3)`, since that combination can misattribute early-January/
late-December boundary dates to the wrong week-year (`YEARWEEK` returns the
correctly-paired ISO year+week directly). Mode 3 avoids MySQL's default mode
0's "week 0" partial-week ambiguity in early January. When the current year
has an ISO week 53 with no matching week 53 a year prior, fall back to
comparing against that prior year's week 52 rather than leaving the
comparison null. Documentation-only change — no application code.

### Acceptance criteria

- [ ] Query added to `grafana/mariadb/queries.md`, grouping by
      `YEARWEEK(date, 3)` (not `YEAR(date)` + `WEEK(date, 3)` separately)
- [ ] Raw YoY % change and a 4-week trailing moving average of that % are
      both present as separate series in the same query/panel
- [ ] The week-53-fallback-to-week-52 rule is implemented and called out in
      an inline comment in the query, given it's a non-obvious edge case
- [ ] Query produces a distinct row per energy

---

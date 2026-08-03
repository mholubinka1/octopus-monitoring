# Periodic Consumption Backfill Job

## Problem Statement

Octopus's consumption API has a real settlement lag — a calendar day can sit at 2/48 or 46/48 half-hourly rows for a day or more after it ends (confirmed live: 2026-07-25 was still 46/48 six days later). Today, gaps only get re-checked two ways: the hourly `consumption_refresh` cursor, which only stalls-and-retries the one day it's currently sitting on, and the Startup Backfill, which re-fetches the full retention window but only runs on process restart. A day that falls behind the hourly cursor's watermark, or a permanent gap Octopus never backfills, has no periodic mechanism to catch it while the process runs long-term without restarting — the container's restart cadence (updates, crashes) is not a reliable substitute for a schedule.

## Solution

Register a new daily scheduled job, `consumption_backfill`, that re-runs the same full-retention-window `ConsumptionRetriever.retrieve()` call the Startup Backfill already makes, at `DAILY_JOB_TIME` — the same cadence as `cost_forecast_refresh` and `update_consumption_summary`. This makes the self-healing described in [ADR-0009](../adr/0009-day-completeness-guard-standing-charge-fallback.md) periodic and observable via `job_run`, rather than contingent on how often the container happens to restart.

## User Stories

1. As the operator of a long-running, rarely-restarted deployment, I want the full consumption retention window to be re-verified daily, so that a day that fell behind the hourly cursor or was permanently under-delivered by Octopus gets caught without waiting for a restart.
2. As someone monitoring the health dashboard, I want this daily re-fetch to log its own `job_run` row under a distinct job name, so that its success/failure history is visible independently of the hourly `consumption_refresh` cursor job.
3. As a maintainer reading the code later, I want the reasoning for re-fetching the full window (rather than querying for just the incomplete days) and for not guarding the resulting cursor race recorded in an ADR, so I don't "fix" either decision without understanding the trade-off already considered.

## Implementation Decisions

- **New job**: `consumption_backfill`, registered in `app/main.py` alongside `register_jobs`, `register_pricing_job`, `register_consumption_summary_job`, `register_cost_forecast_refresh_job`.
  - Schedule: `scheduler.every().day.at(DAILY_JOB_TIME)` — same pattern as `register_cost_forecast_refresh_job`.
  - `job_run` name: new constant `CONSUMPTION_BACKFILL_JOB = "consumption_backfill"`, distinct from `CONSUMPTION_REFRESH_JOB` — kept separate so the hourly cursor job's success/failure history isn't conflated with a differently-timed daily job.
  - Uses the existing `_schedule_refresh_job` / `_with_backoff_recording` / `_run_with_backoff_in_background` helpers unchanged — same retry-with-backoff and `job_run` recording as every other job.
- **Retention-window computation shared with `startup()`**: extract the `period_from` computation currently inlined in `startup()` (`current_time - timedelta(days=refresh_config.retention)`, floored to a UTC date) into a small shared helper, so both `startup()` and the new job compute it identically, and the new job recomputes it fresh on every daily tick (not fixed at registration time).
- **Full window, not targeted**: the job calls `consumption.retrieve(period_from=<recomputed limit>)` unconditionally — the same call `startup()` makes — rather than querying `consumption` for which specific days are still incomplete. See [ADR-0011](../adr/0011-periodic-consumption-backfill-full-window-reuse.md) for why targeting was rejected.
- **Concurrency**: this job shares the `ConsumptionRetriever` instance (and its in-memory `_latest_retrieved_date` cursor dict) with the hourly `consumption_refresh` job. No locking or overlap guard is added — the resulting race is accepted as harmless, matching the precedent already documented in `main()`'s comment about the yearly-comparison backfill racing the eager pricing sync. See ADR-0011.
- **Scope**: consumption only. Pricing (`PricingRetriever`/`product_rate`) is explicitly out of scope for this change.
- **Domain docs updated inline**: `.agent-docs/context.md`'s **Startup Backfill** term amended to note it's no longer restart-only; new **Consumption Backfill Job** term added. New ADR-0011 written.

## Testing Decisions

- Test seam: `app/main.py`'s `register_*_job` functions, exactly as already exercised in `tests/test_refresh_scheduling.py` — register the job against a real `Scheduler`, pass a `Mock(spec=ConsumptionRetriever)`, and assert against the real `mariadb_client` fixture. No new test infrastructure.
- Cover, mirroring the existing `register_cost_forecast_refresh_job` tests:
  - The job is registered daily at `DAILY_JOB_TIME` (`job.unit == "days"`, `str(job.at_time) == "04:00:00"`).
  - A successful run calls `consumption.retrieve(period_from=...)` (not `.refresh()`) and records a successful `job_run` under `consumption_backfill`.
  - A persistently failing run retries with exponential backoff and records failure `job_run`s under `consumption_backfill`, matching `test_persistently_failing_refresh_retries_with_exponential_backoff`'s shape.
  - The `period_from` passed to `retrieve()` reflects the configured `retention_days`, recomputed at call time (not frozen at registration) — worth a direct assertion on the `Mock`'s call args, given this is the detail distinguishing this job from a plain re-registration of `register_jobs`.
- No changes needed to `ConsumptionRetriever`, `MariaDBClient`, or the upsert/write path — those are exercised by their own existing test files (`test_consumption_retrieval.py`, `test_mariadb_upsert.py`) and are unmodified by this change.

## Out of Scope

- Any change to `PricingRetriever` or a similar periodic re-fetch for `product_rate`.
- A targeted/completeness-guard-driven query to find and re-fetch only specific incomplete days.
- Any change to the hourly `consumption_refresh` cursor job's own behavior.
- Locking or coordination between `consumption_backfill` and `consumption_refresh` to prevent concurrent execution.
- Surfacing which specific days were found incomplete/backfilled (job_run remains plain success/failure, no new columns or diffing logic).

## Further Notes

- `DAILY_JOB_TIME` (`"04:00"`) is already shared by every daily/weekly job specifically to avoid landing in watchtower's 03:00 update window (see the comment in `app/main.py`) — the new job reuses the same constant, no new time value introduced.
- This closes the gap between ADR-0009's stated assumption ("settlement lag self-heals within a day or two") and what the code actually guarantees on a long-running container.

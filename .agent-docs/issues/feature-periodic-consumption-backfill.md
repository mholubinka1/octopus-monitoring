# Issues: feature-periodic-consumption-backfill

## Register periodic consumption_backfill job

**Issue**: #459

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Extract the retention-window `period_from` computation currently inlined in `startup()` into a small shared helper, then register a new daily job, `consumption_backfill`, in `app/main.py`'s job-registration set. The job calls `ConsumptionRetriever.retrieve()` with that helper's freshly-recomputed `period_from` — the same full-window call `startup()` already makes — on the same daily cadence and using the same retry-with-backoff/`job_run`-recording helpers as `cost_forecast_refresh` and `update_consumption_summary`. Wire the new job into `main()` alongside the existing `register_jobs`/`register_pricing_job`/etc. calls.

Update `.agent-docs/context.md`'s **Startup Backfill** and **Consumption Backfill Job** terms and ADR-0011 already reflect this design (written during `/grill`) — no further doc changes expected as part of this issue unless implementation surfaces a correction.

### Acceptance criteria

- [ ] The job is registered daily at `DAILY_JOB_TIME` (`job.unit == "days"`, `str(job.at_time) == "04:00:00"`).
- [ ] A successful run calls `ConsumptionRetriever.retrieve(period_from=...)` (not `.refresh()`), with `period_from` reflecting the configured `retention_days`, recomputed at call time rather than frozen at registration.
- [ ] The run records a successful `job_run` row under the job name `consumption_backfill`.
- [ ] A persistently failing run retries with exponential backoff (same backoff shape as the other jobs) and records failure `job_run` rows under `consumption_backfill`.
- [ ] `startup()` is refactored to use the same shared `period_from` helper, with no behavior change to `startup()` itself.

---

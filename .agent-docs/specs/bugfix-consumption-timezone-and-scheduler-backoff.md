# Fix consumption refresh timezone bug and scheduler retry backoff

## Problem Statement

Two pre-existing bugs were found during live testing on the Pi and are combined into a single fix here, since one masked the severity of the other:

1. `ConsumptionClient.build_api_endpoint_from_params` builds its query string by raw concatenation, `.replace('+00:00', 'Z')`-ing a non-UTC ISO timestamp instead of normalizing it — the identical bug `RateClient` had before PR #397. During BST, `_latest_retrieved_date` (the recurring job's `period_from`) carries a `+01:00` offset from real consumption timestamps, which the raw-concatenated query string mangles. Octopus's API rejects it with `{'period_from': ['Enter a valid date/time.']}`. This was invisible during prior testing because the *startup* backfill always computes `period_from` in UTC — only the *recurring* hourly `consumption_refresh` job hits the bug.
2. Because of bug 1, `consumption_refresh` fails on every run during BST. `_schedule_refresh_job` records the failure but then re-raises — and the `schedule` library only advances a job's `next_run` when its callable does *not* raise. So a persistently-failing job never backs off; it re-fires almost immediately (~90s apart, observed in `job_run` timestamps), hammering the Octopus API.

Neither bug was introduced by recently merged PRs #394/#397/#400 — both are pre-existing, newly discovered during live Pi testing.

## Solution

1. Fix `ConsumptionClient` to build request query parameters the same way `RateClient` now does: a `params` dict with UTC/`Z`-normalized timestamps, passed to `OctopusTransport.get`, rather than a manually concatenated query string. Extract the shared UTC/Z normalization logic (currently `RateClient._to_utc_z` + its params-building) into a common helper used by both `RateClient` and `ConsumptionClient`, since this is the second time the identical bug has shipped in a sibling file.
2. Replace the scheduler's re-raise-on-failure behavior with per-job exponential backoff (1 → 2 → 4 → 8 → 16 minutes across 5 attempts), implemented as retries inside a dedicated background worker thread so the single-threaded scheduler loop is never blocked. Once the 5 attempts are exhausted, the job falls back to the normal `refresh_interval_hours` cadence (no special-cased state needed — the next scheduled tick just starts a fresh worker with a fresh attempt count). A successful attempt at any point resets the count implicitly, for the same reason.

## User Stories

1. As the app operator, I want the recurring consumption refresh job to succeed during BST, so that hourly consumption data keeps flowing without manual intervention when the clocks change.
2. As the app operator, I want a persistently-failing scheduled job (consumption or pricing refresh) to back off exponentially instead of retrying every ~90 seconds, so that a real Octopus API outage doesn't get hammered with rapid-fire requests.
3. As the app operator, I want a failing job to eventually resume its normal hourly cadence rather than giving up permanently, so that transient outages self-heal without a container restart.
4. As a future maintainer, I want the UTC/Z timestamp-normalization logic to exist in one place, not duplicated across `rate.py` and `consumption.py`, so the same bug can't ship a third time.
5. As a future maintainer reading `main.py`, I want the reason threads were introduced into an otherwise synchronous codebase recorded in an ADR, so I don't "simplify" it back to blocking retries.

## Implementation Decisions

- **Shared timezone-normalization helper**: extract `RateClient._to_utc_z` (the `ArgumentError`-on-naive-datetime + UTC/`Z` normalization) into a new shared module under `app/data/octopus/` (e.g. `app/data/octopus/params.py`), exposing a function usable by both `RateClient._build_params` and a new equivalent in `ConsumptionClient`. Both clients build a `params: Dict[str, Any]` (`page_size`, optionally `period_from`/`period_to`) and pass it to `OctopusTransport.get(..., params=params)`, instead of `ConsumptionClient` continuing to concatenate a query string onto `api_endpoint`.
- **`ConsumptionClient.build_api_endpoint_from_params`**: changes shape — it currently returns a single query-string-laden URL. It will instead be split (or repurposed) to return the bare endpoint plus a separate `params` dict, mirroring `RateClient._endpoint` / `RateClient._build_params`. `get_electricity_consumption`/`get_gas_consumption` pass both through to `get_consumption_directly_from_endpoint`, which passes `params` to `self._transport.get(...)`. Pagination via Octopus's own returned `next` URL is unaffected (as with `RateClient`, only the first page's request needs `params`; subsequent pages follow the URL Octopus already returned as-is).
- **Scheduler backoff — `_schedule_refresh_job`** (`app/main.py`): the `refresh()` closure registered with `schedule` always dispatches the real work to a background `daemon` thread and returns immediately (never runs `refresh_fn` inline in the scheduler thread). A per-job closure variable tracks the current worker thread; if a worker is already alive for that job when `refresh()` is invoked again, the invocation is skipped (logged), not queued.
- **`retry_with_exponential_backoff` decorator** (new, in `app/common/decorator.py` alongside the existing `retry`): parameterized by `max_attempts` (5), `base_delay_seconds` (60), `multiplier` (2). Wraps the per-attempt function (which itself calls `refresh_fn()` then `mariadb.record_job_run(job_name, "success")`, or on exception calls `mariadb.record_job_run(job_name, "failure", error=str(e))`). Sleeps `base_delay_seconds * multiplier**(attempt-1)` between failed attempts; after the final attempt fails, logs a "giving up until next scheduled run" message and returns without raising, so the daemon thread ends cleanly (no `threading.excepthook` noise, no propagation anywhere).
- **`Job.run()` return value**: the `refresh()` closure returns the started `Thread` object (schedule's `Job.run()` returns whatever the callable returns, and ignores it for scheduling purposes) — this exists purely so tests can `.join()` the thread deterministically instead of sleeping/polling.
- **ADR-0007** (already recorded, see `.agent-docs/adr/0007-background-worker-threads-for-retry-backoff.md`): documents why threads were introduced and why the blocking-decorator alternative was rejected.

## Testing Decisions

- **Consumption timezone fix**: extend `tests/test_consumption_endpoint_building.py` (or replace it, since the interface changes from "returns a URL string" to "returns endpoint + params") and mirror `tests/test_electricity_rate_seam.py`'s `test_a_non_utc_period_is_normalized_to_utc_z_format_in_the_request` / `test_a_naive_period_is_rejected_rather_than_silently_using_local_time` — using `responses` to assert the actual outgoing request's query params via `parse_qs(urlparse(...).query)`, at the `OctopusEnergyAPIClient` seam (highest available seam, same as the rate tests), not by inspecting the private builder method directly.
- **Scheduler backoff**: extend `tests/test_refresh_scheduling.py`. `test_failed_refresh_is_recorded_as_a_failed_job_run_and_still_raises` no longer holds as written — `job.run()` must no longer raise or block, since it dispatches to a thread. New/updated tests should: (a) mock `refresh_fn` to fail every call, drive the returned worker thread via `.join()`, and assert exactly 5 `job_run` "failure" rows recorded with the expected delay sequence (patching `time.sleep` the same way `test_consumption_response_missing_a_required_field_raises_a_clear_validation_error` already patches `common.decorator.time.sleep`, to avoid a real 31-minute test); (b) assert a second `refresh()` invocation while a worker is still alive is skipped (no new thread, no duplicate `job_run` row); (c) assert a successful attempt records a single "success" row and the worker thread ends.
- **Live check**: after the BDD loop, run the app against the real Octopus API and MariaDB on the Pi (`docker compose up -d` in `~/octopus-monitoring-test`) and confirm the recurring `consumption_refresh` job succeeds on its normal (non-failing) path — not a forced-failure live test, since that's covered by the BDD backoff tests above.

## Out of Scope

- Any change to `refresh_interval_hours` configuration semantics or the pricing job's business logic itself.
- Alerting/notification on repeated job failures.
- Persisting retry/backoff state across process restarts (in-memory only, resets on restart — consistent with `ConsumptionRetriever`'s existing in-memory `_latest_retrieved_date` watermark).
- Any dashboard/UI change to visualize backoff state.
- The concurrent `feature/yearly-consumption-comparison` / `chore/consumption-data-pruning` / `feature/pricing-data` branches and the `retention_days` 400-vs-45 tension they raise — explicitly deferred to a separate session per the user's direction.

## Further Notes

- This is the second time the UTC/Z timestamp bug has shipped in a sibling file (`rate.py` then `consumption.py`); the shared-helper extraction exists specifically to prevent a third occurrence.
- This is the first use of threading anywhere in this codebase, which was previously a fully synchronous poll loop — see ADR-0007 for why.

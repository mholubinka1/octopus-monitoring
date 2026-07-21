# Issues: bugfix-consumption-timezone-and-scheduler-backoff

## Extract shared UTC/Z timestamp normalization helper

**GitHub issue**: #409

**Blocked by**: None

**User stories**: 4

### What to build

Extract `RateClient._to_utc_z`'s logic (reject naive datetimes with `ArgumentError`, otherwise normalize to UTC and format with a trailing `Z`) into a small shared module under `app/data/octopus/`, consumed by `RateClient._build_params`. Purely a prefactor — no behavioral change to `RateClient`, and no new public surface beyond the shared function itself. This unblocks the consumption fix in the next slice, which needs the identical normalization.

### Acceptance criteria

- [ ] A timezone-aware, non-UTC datetime normalizes to UTC with a trailing `Z`, matching `RateClient`'s current behavior exactly
- [ ] A naive datetime raises `ArgumentError` with a message containing "timezone-aware", matching the existing message verbatim (an existing test asserts on this exact text)
- [ ] `tests/test_electricity_rate_seam.py` and `tests/test_gas_rate_seam.py` pass unchanged after the extraction

---

## Fix ConsumptionClient's timezone/URL-encoding bug

**GitHub issue**: #410

**Blocked by**: #409 (shared UTC/Z helper)

**User stories**: 1, 4

### What to build

Replace `ConsumptionClient.build_api_endpoint_from_params`'s raw string concatenation with the shared UTC/Z helper from the previous slice, building a `params` dict (`page_size`, `order_by=period`, and optionally `period_from`/`period_to`) passed to `OctopusTransport.get`, mirroring `RateClient`'s request-building shape. `get_consumption_directly_from_endpoint` gains an optional `params` argument defaulting to `None`, so the existing pagination path (which calls it with just the `next` URL Octopus already returned, no params) is unaffected — consistent with how `RateClient` already handles pagination.

### Acceptance criteria

- [ ] A BST-offset (`+01:00`) `period_from`/`period_to` is normalized to UTC/`Z` in the actual outgoing request's query params (verified via a `responses`-mocked request at the `OctopusEnergyAPIClient` seam, mirroring `test_electricity_rate_seam.py`'s BST test)
- [ ] A naive `period_from`/`period_to` raises `ArgumentError` rather than silently using local time
- [ ] `order_by=period` is still present in the outgoing request's params — easy to lose when switching to the rate.py-style helper, since rate.py's params have no equivalent
- [ ] Pagination (following Octopus's own returned `next` URL) is unaffected — no params re-sent on subsequent pages
- [ ] The recurring `consumption_refresh` job succeeds when run live against the real Octopus API during BST, using a real BST-offset `_latest_retrieved_date` (verified on the Pi)

---

## Exponential backoff for failing scheduled jobs via background worker thread

**GitHub issue**: #411

**Blocked by**: None

**User stories**: 2, 3, 5

### What to build

Add a `retry_with_exponential_backoff` decorator (`app/common/decorator.py`, alongside the existing `retry`) parameterized by `max_attempts=5`, `base_delay_seconds=60`, `multiplier=2`. Change `_schedule_refresh_job` (`app/main.py`) so its `refresh()` closure always dispatches to a background daemon thread rather than running `refresh_fn` inline — guarded per job (via closure state) so a new invocation is skipped and logged whenever a worker is already alive for that job, regardless of whether the existing worker is retrying or simply still completing a normal run. The decorator wraps the per-attempt logic (call `refresh_fn`, then record `job_run` success/failure) inside that thread; after 5 exhausted attempts it logs and returns without raising, so the thread ends cleanly and the next scheduled tick starts a fresh attempt count. Applies uniformly to both `register_jobs` (consumption) and `register_pricing_job` (pricing), since both share `_schedule_refresh_job`. The `refresh()` closure returns the started `Thread` so tests can `.join()` it deterministically. Recorded as ADR-0007.

### Acceptance criteria

- [ ] A job whose `refresh_fn` fails every attempt makes 5 attempts total, with gaps of 1, 2, 4, then 8 minutes between them, recording a `job_run` "failure" row each time
- [ ] After the 5th attempt fails, the worker thread ends without raising, and the next scheduled tick starts a fresh attempt count (no permanent give-up, no `next_run` manipulation needed)
- [ ] A new `refresh()` invocation is skipped and logged (not double-started) whenever a worker thread is already alive for that job — whether it's mid-backoff-retry or simply still completing a normal (successful) run
- [ ] A successful `refresh_fn` call records exactly one `job_run` "success" row and the worker thread ends
- [ ] This behavior is identical for both the consumption and pricing refresh jobs
- [ ] After merge, live-verify on the Pi that the normal (non-failing) path still runs correctly under the new threaded dispatch

---

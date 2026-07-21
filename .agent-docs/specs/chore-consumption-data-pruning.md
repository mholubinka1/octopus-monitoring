# Consumption Data Pruning

## Problem Statement

ADR-0003 has documented a retention policy since before the app's first real deployment, but the pruning job it describes has never actually existed — raw `consumption` and `product_rate` data has grown unbounded the entire time, on Pi-class hardware where that's a real operational risk. The retention window was widened to 400 days specifically so raw data could carry a year-plus of dashboard history, but `feature/yearly-consumption-comparison` (this branch's dependency) now carries that long-term view in a purpose-built, pruning-exempt aggregate table instead — so raw retention no longer needs to be that deep, and the pruning job that was deferred for over a year can finally be built without losing anything the dashboard actually needs.

## Solution

Revert `retention_days` to 45, implement the weekly pruning job the ADR always described, and gate it on that cycle's aggregation job having succeeded so raw data is never deleted before it's rolled into `daily_consumption_summary`. Because reverting the window immediately would orphan the year-plus of history the yearly-comparison charts need, ship a one-time manual migration that rebuilds the database from a deep 2-year backfill before the shorter window and pruning take effect.

## User Stories

1. As the operator, I want raw `consumption` and `product_rate` data older than 45 days actually deleted, so that MariaDB's storage footprint stays bounded on Pi-class hardware, matching what ADR-0003 has described since before this app was first deployed.
2. As the operator, I want the pruning job to never run against a week whose data hasn't yet been rolled into `daily_consumption_summary`, so that a transient aggregation failure can't silently erase history the yearly-comparison charts still need.
3. As the operator, I want a clearly documented, deliberate one-time step to migrate from the current 400-day-deep database to the new 45-day window without losing the 2 years of history the yearly-comparison feature needs, so that shipping this chore doesn't quietly throw away data I can't get back.
4. As a future reader of this repo (human or agent), I want ADR-0003 to describe what's actually implemented, not a still-future intention, so that the ADR stops being a standing "this doesn't exist yet" caveat.

## Implementation Decisions

- **`retention_days` reverts 400 → 45** in `config.yml.template` and the README's Configuration section field description (which currently says it "doubles as the intended retention window" — that phrasing is now literally true rather than aspirational, but the number changes back down). No change to `RefreshSettings`/`app/common/config.py` itself — `retention` already reads whatever `retention_days` says; only the value changes.
- New weekly job `prune_old_data`, registered on the same weekly schedule as `feature/yearly-consumption-comparison`'s `update_consumption_summary` job, and run immediately after it in the same scheduling tick:
  - Deletes `consumption` rows where `period_from` is older than `retention_days`.
  - Deletes `product_rate` rows where `valid_to` is older than that same cutoff — a still-valid or currently-open-ended (`valid_to IS NULL`) rate is never pruned regardless of the row's age.
  - Does **not** touch `agreement` — it's small (one row per tariff-contract period, changes rarely) and needed to interpret which product applied to whatever `consumption`/`product_rate` history remains; pruning it doesn't address any real storage concern.
  - A single `DELETE ... WHERE ...` statement per table, no batching/chunking — at 45-day retention with half-hourly data for two meters, a week's worth of newly-expired rows is a few thousand at most, well within what a single statement can delete on a Pi without meaningful lock contention.
- **Gating on aggregation success**: before running, `prune_old_data` checks whether that same scheduling cycle's `update_consumption_summary` job (from `feature/yearly-consumption-comparison`) recorded a successful `job_run`. If it didn't (failed, or hasn't run yet this cycle), pruning is skipped for this cycle — logged, and recorded as its own outcome via `job_run` — rather than risking deletion of raw data that hasn't yet been summarized. Implemented as a small guard function reading the latest `job_run` row for `update_consumption_summary`, called from the same job-registration path used for the other scheduled jobs — as of `bugfix/consumption-timezone-and-scheduler-backoff`, that's `_schedule_refresh_job`'s background-worker-thread-with-backoff mechanism, not the plain try/except this spec originally assumed.
- **One-time migration**, run manually once before this chore's shorter window takes effect (never automated into ordinary app startup — this project's established stance, per [ADR-0005](../adr/0005-additive-only-schema-sync.md), is that destructive data operations stay deliberate and outside the automated tooling):
  - A standalone script (e.g. `scripts/rebuild_history.py`), separate from `main.py`'s normal entrypoint.
  - Truncates `consumption`, `agreement`, `product`, `product_rate`, `daily_consumption_summary`, and `job_run` — plus `cost_forecast`/`agile_forecast` if `feature/agile-cost-forecast` has landed by the time this chore is implemented (whichever of the two ships first should confirm the other's table list here rather than one silently going stale).
  - Re-runs a deep historical backfill — 2 years, not the new 45-day `retention_days` — reusing `ConsumptionRetriever`/`PricingRetriever` against that explicit lookback rather than the config-driven one.
  - Runs `feature/yearly-consumption-comparison`'s aggregation logic across the full re-backfilled range to seed `daily_consumption_summary` with 2 years of daily totals (enough for every week in the yearly-comparison panel's 52/53-week window to have a valid year-ago comparator).
  - Documented as an explicit runbook step (README or a dedicated migration note): stop the app, run the script, then restart normally under the new 45-day config.
- **ADR-0003** updated in place to record that the pruning job described since the ADR's first revision is now actually implemented, at the reverted 45-day window, with the aggregate-table rationale for why 400 days is no longer needed (this may already be reflected from `feature/yearly-consumption-comparison`'s branch — this chore is what actually ships the job the ADR describes and confirms the text matches the shipped behaviour).

## Testing Decisions

- **`prune_old_data`**: tested against a seeded SQLite in-memory session (the same seam already used by `test_pricing_retrieval.py`), asserting:
  - `consumption`/`product_rate` rows older than the cutoff are deleted; rows within the window (and `product_rate` rows with `valid_to IS NULL` or a future `valid_to`) are untouched regardless of `valid_from` age.
  - `agreement` rows are never deleted, even ones far older than the cutoff.
- **Gating behaviour**: extend `test_refresh_scheduling.py`'s existing pattern (`Mock(spec=...)`, asserting `job_run` outcomes) — given the latest `update_consumption_summary` `job_run` row is a failure (or absent), running the scheduled tick records `prune_old_data` as skipped and performs no deletions; given it's a success, pruning proceeds and its own outcome is recorded.
- **`scripts/rebuild_history.py`**: no automated test suite — this is a manual operational tool run once, by design, not part of the app's regular code path. Verified the same way `chore/consolidate-mariadb-env-config`'s infrastructure change was verified: by actually running it against the real deployment during the planned migration, and confirming the resulting `daily_consumption_summary`/raw table contents match expectations.

## Out of Scope

- Building `daily_consumption_summary` or the `update_consumption_summary` job itself — that's `feature/yearly-consumption-comparison`, this chore's dependency.
- Batched/chunked deletion — explicitly decided against; current data volume at 45-day retention doesn't warrant the added complexity.
- Any change to `cost_forecast`/`agile_forecast`'s pruning-exempt status — unaffected by this chore.
- Automating the one-time migration into app startup — deliberately kept manual, per ADR-0005's precedent.

## Further Notes

This chore is stacked on `feature/yearly-consumption-comparison` and cannot land before it — the gating check depends on `update_consumption_summary`'s `job_run` records existing, and the migration script seeds `daily_consumption_summary`, which that branch defines. Full rationale is recorded in this session's `/grill` transcript and in the revised [ADR-0003](../adr/0003-90-day-data-retention.md).

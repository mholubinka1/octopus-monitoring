# Issues: chore-consumption-data-pruning

## Revert retention_days to 45 (#406)

**Blocked by**: None

**User stories**: 1 (foundational)

### What to build

Revert `config.yml.template`'s `retention_days` from `400` back to `45`, and
update the README's Configuration section description accordingly — raw
data no longer needs to carry a year-plus of history now that
`daily_consumption_summary` (from `feature/yearly-consumption-comparison`)
does. No code change: `RefreshSettings`/`app/common/config.py` already reads
whatever `retention_days` says; only the value and its documentation change.
This is non-destructive on its own (it only shrinks the startup backfill's
lookback) and can land independently of the pruning job itself.

### Acceptance criteria

- [ ] `config.yml.template`'s `retention_days` is `45`
- [ ] README's Configuration section description matches the reverted value
      and explains why (long-term history now lives in
      `daily_consumption_summary`, not raw data)
- [ ] `tests/test_config_settings.py` still passes unchanged (it doesn't
      assert on the specific production default, only the parsing mechanism)
- [ ] Existing test suite remains green

---

## Weekly raw-data pruning job (#407)

**Blocked by**: #406 (Revert retention_days to 45), #403 (Schedule the weekly
consumption-summary job, from `feature/yearly-consumption-comparison`)

**User stories**: 1, 2, 4

### What to build

New scheduled job `prune_old_data`, registered on the same weekly schedule as
`update_consumption_summary` and run immediately after it in the same tick.
Deletes `consumption` rows where `period_from` is older than
`retention_days`, and `product_rate` rows where `valid_to` is older than that
same cutoff (a still-valid or open-ended `valid_to IS NULL` rate is never
pruned). Never touches `agreement`. Single `DELETE` statement per table, no
batching. Before running, checks whether that cycle's
`update_consumption_summary` job recorded a successful `job_run`; if not
(failed or hasn't run yet this cycle), skips pruning for this cycle and
records that outcome via its own `job_run` row, so raw data is never deleted
before it's been rolled into `daily_consumption_summary`. Also update
ADR-0003 in place to confirm it now describes shipped behaviour, not future
work.

### Acceptance criteria

- [ ] `consumption` rows older than `retention_days` are deleted;
      `product_rate` rows with `valid_to` older than the cutoff are deleted;
      rows within the window, and `product_rate` rows with `valid_to IS NULL`
      or a future `valid_to`, are untouched
- [ ] `agreement` rows are never deleted, regardless of age
- [ ] Given the latest `update_consumption_summary` `job_run` is a failure
      (or absent), `prune_old_data` performs no deletions and records its own
      `job_run` reflecting the skip
- [ ] Given the latest `update_consumption_summary` `job_run` is a success,
      pruning proceeds and records its own successful `job_run`
- [ ] ADR-0003 reflects the shipped 45-day/pruning-implemented state
- [ ] Existing test suite remains green

---

## One-time database rebuild migration script (#408)

**Blocked by**: #401 (Daily consumption summary schema), #402 (Populate
daily_consumption_summary from raw consumption) — both from
`feature/yearly-consumption-comparison`

**User stories**: 3

### What to build

Standalone script `scripts/rebuild_history.py`, separate from `main.py`'s
normal entrypoint, never invoked automatically on app startup. Truncates
`consumption`, `agreement`, `product`, `product_rate`,
`daily_consumption_summary`, and `job_run` — plus `cost_forecast`/
`agile_forecast` if `feature/agile-cost-forecast` has landed by the time
this issue is implemented (whichever of the two ships first should confirm
the other's table list here rather than one silently going stale);
re-runs a deep historical
backfill (2 years, an explicit lookback rather than the config-driven
`retention_days`) via `ConsumptionRetriever`/`PricingRetriever`; then runs
`ConsumptionSummaryRetriever`'s aggregation logic across the full
re-backfilled range to seed `daily_consumption_summary` with 2 years of
daily totals. Documented as an explicit manual runbook step (stop the app,
run the script, restart normally under the reverted 45-day config) to be
carried out once, before this chore's shorter retention window and pruning
job take effect.

### Acceptance criteria

- [ ] Running the script against a populated database truncates the listed
      tables (including `cost_forecast`/`agile_forecast` if they exist by
      then) and repopulates them from a 2-year Octopus backfill
- [ ] `daily_consumption_summary` ends up seeded with daily totals for the
      full 2-year range, sufficient for every ISO week in the yearly
      comparison panel's 52/53-week window to have a valid year-ago
      comparator
- [ ] The script is never invoked from `main.py`'s normal startup path
- [ ] A runbook step documenting when and how to run it is added (README or
      a dedicated migration note)
- [ ] No automated test suite for the script itself (manual operational
      tool, by design) — verified by running it during the real migration

---

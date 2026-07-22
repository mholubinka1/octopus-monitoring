# Cost forecast: current-agreement lookup must handle bounded valid_to

## Problem Statement

`cost_forecast.refresh()` fails every time it runs for accounts whose current
electricity agreement has a real (non-null) `valid_to` — which is the normal
shape for Agile-tariff accounts, since Octopus renews Agile contracts as
fixed one-year terms and never returns `valid_to: null`, not even for the
currently-active agreement. Confirmed live on a real Agile-tariff account:
the daily 04:00 scheduled job and the startup call both catch and log the
resulting `RuntimeError` non-fatally, so the failure is silent in normal
operation — but permanent. `agile_forecast` and `cost_forecast` stay
permanently empty for any account in this shape.

## Solution

`CostForecastRetriever._current_electricity_agreement()` selects "current" by
range-containment (`valid_from <= as_of AND (valid_to IS NULL OR as_of <
valid_to)`) instead of requiring `valid_to IS NULL`. This matches the
convention already used elsewhere in this codebase for the same kind of
lookup (`app/data/mysql/client.py`'s `read_current_product_rate` and the
consumption-to-agreement join), so agreements with a bounded `valid_to` that
still covers `as_of` are found correctly, while genuinely open-ended
agreements (`valid_to IS NULL`) keep working exactly as before.

## User Stories

1. As the daily cost-forecast job, I want to find the electricity agreement
   that covers "now" even when that agreement has a real end date, so that
   `refresh()` succeeds for Agile-tariff accounts instead of raising every
   time it runs.
2. As a developer reading this code, I want the "current agreement" lookup to
   use the same range-containment convention as the other "current as of a
   point in time" lookups in this codebase, so that the logic is predictable
   and consistent across the pricing pipeline.
3. As the cost-forecast job, I want a clear, actionable error when no
   agreement's range actually contains `as_of` (e.g. a genuine gap between
   one contract ending and its renewal starting), so that failures remain
   loud rather than silently producing a wrong forecast.

## Implementation Decisions

- `app/data/cost_forecast.py`: `_current_electricity_agreement()` gains a
  required `as_of: datetime` parameter. Its selection predicate changes from
  `a.valid_to is None` to `a.valid_from <= as_of and (a.valid_to is None or
  as_of < a.valid_to)`.
- The call site in `refresh()` (already has `as_of` in scope) passes it
  through: `self._current_electricity_agreement(as_of)`.
- The `RuntimeError` message for the no-match case is reworded since "open-
  ended" is no longer the criterion (still matches the existing test's
  `"[Nn]o current .*agreement"` regex).
- No change to `Agreement`, no change to any MySQL query — this is an
  in-memory selection over `electricity_meter.agreements`, mirroring the
  SQL-level pattern rather than moving the lookup into SQL.
- Overlapping-agreement ambiguity is not defensively handled: `next()` takes
  the first matching agreement in list order. Octopus's data model doesn't
  produce overlapping agreements for one meter, and no real fixture has
  shown this, so speculative handling isn't warranted.
- No ADR: this mirrors an existing, already-decided convention rather than
  introducing a new one.

## Testing Decisions

- Test at the existing seam: `CostForecastRetriever.refresh()` via the
  `_RealCostForecastSource` test double in
  `tests/test_cost_forecast_retriever.py` (real `MariaDBClient`/SQLite
  fixture underneath, HTTP mocked via `responses`) — the same seam every
  other test in that file already uses.
- New regression test: a current agreement with a bounded, non-`None`
  `valid_to` that still spans `as_of` (mirroring the real Agile account's
  fixture shape) — asserts `refresh()` does not raise and persists a
  forecast row. All 12 existing fixtures in this file use `valid_to=None`
  for the current agreement, which structurally hid this exact bug.
- Existing test `test_no_current_agreement_raises_a_clear_error` continues
  to cover the genuine-no-match case (its agreement's `valid_to` already
  precedes `as_of`) and should still pass unchanged against the reworded
  error message, since the regex only checks for `"no current .*agreement"`.
- No changes needed to the other 11 existing tests — unaffected, still valid
  coverage for the open-ended (`valid_to IS NULL`) case.

## Out of Scope

- The Pi redeployment and resumption of the paused live-monitoring window
  (manual follow-up once this merges and CI publishes a new image).
- The CI push-trigger investigation (separate, already owned by another
  agent per the handoff).
- The `pi-desktop/docker/docker-compose.yml` service-definition merge
  (tracked separately, file-edit-only, no redeploy of that stack).

## Further Notes

Handoff document: `octopus-monitoring-handoff-9.md`. Investigation already
confirmed live against the Pi deployment's real `agreement` table for a real
Agile-tariff account (see handoff for the exact row shapes observed). Same
masking pattern already flagged in the PR #423 review per project memory
(`project_octopus_monitoring_pricing_pipeline`) — fixture data that
coincidentally simplifies away the real-world case.

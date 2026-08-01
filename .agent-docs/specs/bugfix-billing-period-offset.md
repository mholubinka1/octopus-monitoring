# Billing Period Off-By-One-Day Fix

## Problem Statement

`BillingPeriod.from_billing_options` consumes Kraken's `currentBillingPeriodStartDate`/
`currentBillingPeriodEndDate` verbatim. These fields report Octopus's account
statement/ledger window (previous-balance-date to new-balance-date), not the tariff
charge window Octopus actually bills consumption against. The two are offset by
exactly one day on both ends, confirmed across 6 consecutive real bills for this
account (Feb–July 2026), with zero exceptions.

Live confirmation via this repo's existing research (`.agent-docs/research/octopus-billing-period-api.md`,
smoke-tested 2026-07-21): this account is on **flexible billing** (`isFixed: false`),
so Kraken never supplies a real end date — `_add_one_month_clamped(period_start)` does
100% of the end-date computation in production today, and it uses the wrong framing
("same day-of-month next month") for this account's actual cycle shape ("day-of-month
minus 1, next month").

`CostForecastRetriever.refresh` (`app/data/cost_forecast.py`) uses `billing_period.start`/
`end` as the basis for `elapsed_start`, `total_period_days`, `remaining_days`,
`remaining_hours`, and `period_end_boundary`. Being wrong on both ends means
`actual_cost_to_date` silently omits the first real day of each period's consumption
and cost, and `projected_total_cost` is computed against the wrong period length. This
has been wrong since the app went live — not a new regression.

## Solution

Shift the dates inside `BillingPeriod.from_billing_options` (not at the Kraken client
boundary — `kraken.py`/`BillingOptionsData` stays an honest, unmodified mirror of
Kraken's raw response) so the resulting `BillingPeriod` reflects the actual tariff
window, not Kraken's ledger window:

1. Adjust `period_start` back by one day once, up front, to recover the true tariff
   start.
2. Fixed billing (`is_fixed: True`): `end = period_end - 1 day` (Kraken's raw end,
   shifted independently — this branch doesn't currently execute for this account
   since it's on flexible billing, but is kept correct for portability/future-proofing).
3. Flexible billing (`is_fixed: False`): `end = _add_one_month_clamped(adjusted_start) - 1 day`.
   The extra day beyond the adjusted start is necessary because this account's real
   cycle shape is `[day X, day X−1 of next month]`, not `[day X, day X (same) of next
   month]` — confirmed by comparing consecutive real bills (e.g. `6th April → 5th May`
   statement / `5th April → 4th May` tariff, then `6th May → 5th June` statement /
   `5th May → 4th June` tariff).

## User Stories

1. As the operator, I want `cost_forecast.actual_cost_to_date` to include every day of
   consumption actually billed in the current period, so the "cost so far" figure
   matches what Octopus will actually charge.
2. As the operator, I want `projected_total_cost` computed against the real tariff
   period length, so the forecast isn't silently skewed by a phantom extra day.
3. As a developer, I want the billing-period date logic verified against the account's
   real, observed cycle shape (not just the ledger/tariff start offset), so a fix for
   one off-by-one bug doesn't leave a second one in place.

## Implementation Decisions

- **`app/data/octopus/model.py`** — `BillingPeriod.from_billing_options`:
  - Compute `adjusted_start = period_start - timedelta(days=1)` once, before branching
    on `is_fixed`.
  - `is_fixed=True` branch: keep the existing null-check (still refuses to guess a
    fallback date if Kraken reports `isFixed: true` with no end date), then return
    `start=adjusted_start, end=period_end - timedelta(days=1)`.
  - `is_fixed=False` branch: return
    `start=adjusted_start, end=_add_one_month_clamped(adjusted_start) - timedelta(days=1)`.
  - `_add_one_month_clamped` itself is unchanged — it's a general-purpose "same
    day-of-month, one month later, clamped" helper; the caller now applies the
    additional day as part of interpreting its output as this account's actual cycle
    boundary, not inside the helper.
- **`kraken.py` / `BillingOptionsData`** — unchanged. Continues to be a direct,
  unmodified mirror of Kraken's GraphQL response, for debuggability.
- **`.agent-docs/context.md`** — "Billing Period" glossary entry already updated
  in-line to describe the corrected date semantics (done during the grill session).
- **No change** to `CostForecastRetriever`, `MariaDBClient.write_cost_forecast`, or any
  Grafana query — they all consume `BillingPeriod`/`CostForecast` values as given; the
  fix is entirely upstream of them.

## Testing Decisions

- Test seam: `tests/test_kraken_billing_period.py` already exercises exactly this path
  end-to-end (mocked Kraken GraphQL responses → `BillingPeriodClient.get_current_billing_period()`
  → asserted `BillingPeriod.start`/`end`). No new seam needed.
- Every existing date assertion in that file needs updating to the shifted values, per
  the tracer-bullet BDD loop (one assertion/case at a time, not a bulk find-replace):
  - `test_isFixed_true_uses_the_kraken_end_date_directly` (renamed to
    `test_isFixed_true_shifts_both_kraken_dates_back_one_day` per Copilot review
    feedback, since its old name implied a pass-through that no longer happens):
    start `2026-07-06→2026-07-05`,
    end `2026-08-05→2026-08-04`.
  - `test_isFixed_false_falls_back_to_start_plus_one_calendar_month` (renamed to
    `test_isFixed_false_derives_the_tariff_window_a_day_before_krakens_ledger_dates`,
    since its old name described the pre-fix behavior): start
    `2026-07-06→2026-07-05`, end `2026-08-06→2026-08-04` (two days off the old value —
    one for the start shift, one for the same-day-of-month framing correction).
  - `test_isFixed_false_clamps_to_the_last_valid_day_of_a_shorter_month`: start
    `2026-01-31` unshifted is `2026-01-30`; end shifts from `2026-02-28` — needs
    recomputing from the adjusted start (`2026-01-30` + 1 month clamped = `2026-02-28`,
    then `-1 day` = `2026-02-27`).
  - `test_isFixed_false_clamps_correctly_across_a_leap_year_february`: recompute
    similarly from the adjusted start.
  - `test_isFixed_false_rolls_over_a_year_boundary`: recompute similarly.
  - `test_isFixed_true_with_no_end_date_raises_rather_than_silently_falling_back`:
    unaffected (still raises before returning any date, real or fabricated).
- New case: a test asserting the "day X, day X−1 of next month" shape specifically for
  a flexible-billing period whose start is *not* near a month boundary (e.g. the 6th),
  to pin the general (non-clamped) behavior independently from the clamping-specific
  cases above.
- Real-world verification (not automatable): once deployed, compare the next
  scheduled `cost_forecast` row's `billing_period_start`/`end` against the real bill
  that eventually posts for that period (~early September, since the August bill
  posted ~6th August covers the period this fix first computes correctly).

## Out of Scope

- Backfilling existing `cost_forecast` rows — `cost_forecast` is append-only history,
  not a rolling snapshot (`write_cost_forecast` always inserts, never upserts onto an
  existing period). Historical rows keep their pre-fix dates. Instead, after this fix
  is deployed, manually purge the table in production (`DELETE FROM cost_forecast`);
  `run_initial_cost_forecast_sync` refills it with correct dates within seconds of the
  app restart that the deploy already causes, so there's no dashboard gap.
- Any change to `CostForecastRetriever`'s own arithmetic (`_project_remaining_cost`,
  `_fill_zero_consumption_days`, etc.) — that logic is already correct given a correct
  `BillingPeriod`; it was never the source of the bug.
- Any change to Grafana panels or `grafana/mariadb/queries.md` — they read whatever
  `cost_forecast` contains; once the table has correct values, they're correct with no
  query changes.
- Verifying the `is_fixed: True` branch against a real bill — this account has never
  been on fixed billing, so there's no real data to check that branch against. The fix
  applies the same evidence-based shift by inference/consistency, not empirical
  confirmation, and is documented as such.

## Further Notes

Discovered while manually building Grafana dashboard panels (`feature/grafana-dashboard`)
and cross-referencing the "Current Billing Period" panel's displayed dates against six
real Octopus PDF bills the user provided. The account-is-flexible-billing fact was
already established in `.agent-docs/research/octopus-billing-period-api.md` from a
prior smoke test — this fix session is the first time that fact was connected to the
observed date discrepancy.

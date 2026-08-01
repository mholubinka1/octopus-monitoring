# Issues: bugfix/billing-period-offset

## Fix flexible-billing branch date offset in BillingPeriod.from_billing_options

**Issue**: #454

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Correct `BillingPeriod.from_billing_options`'s `is_fixed=False` branch — the only
branch this account actually exercises in production (it's on flexible billing per
`.agent-docs/research/octopus-billing-period-api.md`). Shift `period_start` back one
day to recover the true tariff start (Kraken's raw field reports the account statement
window, one day later than the tariff window). Compute the period end from that
adjusted start via the existing `_add_one_month_clamped` helper, then subtract one
further day — this account's real cycle shape is `[day X, day X−1 of next month]`, not
`[day X, day X (same) of next month]`, confirmed across 6 consecutive real bills.

### Acceptance criteria

- [ ] `BillingPeriod.from_billing_options` with `is_fixed=False` returns a start one
      day earlier than the raw `period_start` it's given.
- [ ] The corresponding end is one calendar month after the adjusted start, same
      day-of-month, minus one further day, clamped to the target month's last valid
      day where applicable.
- [ ] `tests/test_kraken_billing_period.py`'s existing flexible-billing test cases
      (`test_isFixed_false_derives_the_tariff_window_a_day_before_krakens_ledger_dates`
      [renamed from `test_isFixed_false_falls_back_to_start_plus_one_calendar_month`],
      `test_isFixed_false_clamps_to_the_last_valid_day_of_a_shorter_month`,
      `test_isFixed_false_clamps_correctly_across_a_leap_year_february`,
      `test_isFixed_false_rolls_over_a_year_boundary`) pass with updated expected
      dates.
- [ ] A new test pins the general (non-clamped) `[day X, day X−1 of next month]` shape
      for a start date not near a month boundary.

---

## Fix fixed-billing branch date offset in BillingPeriod.from_billing_options

**Issue**: #455

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Correct `BillingPeriod.from_billing_options`'s `is_fixed=True` branch for
consistency/portability, even though this account never exercises it today. Shift
both `period_start` and Kraken's raw `period_end` back one day each, independently —
both are raw Kraken ledger-window dates, so both get the same evidence-based shift.
Keep the existing null-`period_end` guard (raises rather than guessing a fallback
date) unchanged.

### Acceptance criteria

- [ ] `BillingPeriod.from_billing_options` with `is_fixed=True` returns a start one
      day earlier than the raw `period_start`, and an end one day earlier than the
      raw `period_end`.
- [ ] `tests/test_kraken_billing_period.py::test_isFixed_true_shifts_both_kraken_dates_back_one_day`
      passes with updated expected dates.
- [ ] `tests/test_kraken_billing_period.py::test_isFixed_true_with_no_end_date_raises_rather_than_silently_falling_back`
      still passes unchanged (still raises before returning any date, real or
      fabricated).

---

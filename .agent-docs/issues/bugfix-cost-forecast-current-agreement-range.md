# Issues: bugfix-cost-forecast-current-agreement-range

## Fix current-agreement lookup to use range containment, not valid_to IS NULL

**GitHub issue**: #425

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Change `CostForecastRetriever._current_electricity_agreement()` to take
`as_of: datetime` and select the electricity agreement whose
`[valid_from, valid_to)` range contains `as_of` (`valid_to IS NULL` treated
as unbounded), instead of requiring `valid_to IS NULL` outright. Thread
`as_of` through from `refresh()`, which already has it in scope. Reword the
no-match `RuntimeError` since "open-ended" is no longer the criterion. Add a
regression test with a bounded, non-`None` `valid_to` that still spans
`as_of`, matching the real Agile-account fixture shape that exposed this bug.

### Acceptance criteria

- [ ] `_current_electricity_agreement(as_of)` selects an agreement using
      `valid_from <= as_of and (valid_to is None or as_of < valid_to)`.
- [ ] `refresh()` passes `as_of` through to `_current_electricity_agreement`.
- [ ] New test: a current agreement with a bounded `valid_to` spanning
      `as_of` results in `refresh()` succeeding and persisting a forecast row.
- [ ] Existing test `test_no_current_agreement_raises_a_clear_error` still
      passes against the reworded error message.
- [ ] All other existing tests in `tests/test_cost_forecast_retriever.py`
      still pass unchanged.

---

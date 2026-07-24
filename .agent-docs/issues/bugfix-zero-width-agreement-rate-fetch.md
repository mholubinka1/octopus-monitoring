# Issues: bugfix-zero-width-agreement-rate-fetch

> Work complete — PR ready to merge.

## Skip rate fetches for zero/negative-width agreements

**GitHub issue**: #431

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

In `PricingRetriever._sync_own_product_rates()`, add a guard before the rate-fetch
call that skips any agreement whose `valid_from` is on or after its `valid_to` (when
`valid_to` is not `None`), for both electricity and gas agreements. Log the skip at
debug level instead of letting the call reach Octopus's API and fail. The guard is
local to `_sync_own_product_rates()` — it does not touch `_meter_agreement_pairs()` or
`_sync_comparison_rates()`, which must keep behaving exactly as before. The existing
`try/except` around the fetch call remains, as a safety net for other failure modes.

### Acceptance criteria

- [x] An electricity agreement with `valid_from == valid_to` never reaches
      `fetch_electricity_rates`, and a debug-level log line is emitted for it.
- [x] A gas agreement with `valid_from == valid_to` never reaches `fetch_gas_rates`,
      and a debug-level log line is emitted for it.
- [x] `_sync_comparison_rates()`'s `own_product_codes` exclusion set is unaffected —
      a skipped agreement's product code still excludes it from comparison-rate
      syncing.
- [x] Existing agreements with valid (non-degenerate) ranges are unaffected — rates
      are still fetched and persisted for them exactly as before.
- [x] Full test suite and pre-commit hooks pass.

---

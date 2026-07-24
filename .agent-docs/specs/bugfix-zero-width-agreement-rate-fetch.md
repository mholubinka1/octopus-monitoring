# Skip rate fetches for zero-width agreements

## Problem Statement

`PricingRetriever._sync_own_product_rates()` fetches rates for every agreement on
every meter, once per hourly `pricing_refresh` run. At least one real account has a
historical agreement whose `valid_from` and `valid_to` are identical
(`VAR-22-11-01`/`E-1R-VAR-22-11-01-C`, both `2025-05-23T23:00:00Z`). Forwarding that
zero-width range straight to Octopus's rates endpoint as `period_from`/`period_to`
always gets a 400 response, because the endpoint rejects identical bounds.

This is already caught by the existing `try/except` around the fetch call, so there is
no data loss and `pricing_refresh` still completes successfully every hour — but the
account pays for 3 wasted, automatically-retried HTTP calls every hour, forever, for
an agreement that can never produce a valid rate window. Nothing will change about
Octopus's historical data to fix this on its own.

## Solution

Recognise the zero/negative-width condition before making the network call, for both
electricity and gas agreements, and skip the fetch entirely rather than relying on the
exception handler to clean up after a guaranteed failure. The skip is logged at debug
level — this is an expected, permanent condition for this agreement, not something
that needs operator attention, but it stays traceable for anyone investigating why an
agreement never gets rates.

## User Stories

1. As the pricing pipeline, I want to recognise agreements whose valid range can never
   produce a rate window, so that I stop making calls to Octopus's API that are
   guaranteed to fail.
2. As an operator reading logs, I want a clear, low-noise trace of why a specific
   agreement's rates are never synced, so that I can distinguish "expected, permanent
   skip" from "transient failure worth investigating."
3. As a future maintainer, I want the existing `try/except` around the fetch call to
   keep catching genuine failures (network errors, other 400s), so that this fix
   narrows the failure surface without removing the safety net.

## Implementation Decisions

- **Module**: `app/data/pricing.py`, `PricingRetriever._sync_own_product_rates()`.
- Add a guard inside the existing loop, immediately before the `fetch_rates(...)`
  call: if `agreement.valid_from >= agreement.valid_to` (only meaningful when
  `valid_to` is not `None`), log at debug level and `continue` — do not call
  `fetch_rates`, do not call `persist_rate`.
- The condition is `>=`, not just `==`, so it also covers a theoretical inverted range
  (`valid_from` after `valid_to`), not only the exact-equality case seen in production.
- The guard applies to both electricity and gas agreements. `_sync_own_product_rates`
  already branches on `meter.energy` to pick `fetch_electricity_rates` vs.
  `fetch_gas_rates` for the same loop body, so placing the guard before that branch
  covers both meter types with no extra code.
- **Do not** move or duplicate this guard into `_meter_agreement_pairs()`. That
  iterator is also consumed by `_sync_comparison_rates()` to build
  `own_product_codes`, the set used to exclude the account's own products from
  comparison-rate syncing (`app/data/pricing.py:109-112`). If the zero-width
  agreement were filtered out at the shared iterator, its product code would stop
  being excluded there too, and the dead product would incorrectly get synced as a
  comparison rate instead — a different waste than the one being fixed. The guard
  must be local to `_sync_own_product_rates()`.
- The existing `try/except Exception` around the fetch call in
  `_sync_own_product_rates()` stays as-is — it remains the safety net for genuine,
  non-permanent failures (network errors, other unexpected 400s). This fix only
  removes the *known, permanent* zero-width case from ever reaching it.

## Testing Decisions

- Test through the existing top seam: `PricingRetriever.refresh()`, using the
  `_RealPricingSource` adapter and fixture-building helpers already established in
  `tests/test_pricing_retrieval.py` (genuine `OctopusEnergyAPIClient` and
  `MariaDBClient` underneath, HTTP mocked via `responses`).
- New regression test: build an electricity meter whose agreement has
  `valid_from == valid_to`, run `refresh()`, and assert via `responses` that the
  electricity rates endpoint was never called for that agreement (no matching
  registered call was made) and that no `product_rate` row was persisted for it.
- Add an equivalent case for a gas agreement with `valid_from == valid_to`, asserting
  the gas rates endpoint is never called, to cover the "applies to both energy types"
  decision.
- Assert the debug-level log message is emitted (via `caplog`), to lock in the chosen
  log level as a regression guard against it silently reverting to `warning` or
  disappearing entirely.
- Existing fixtures in this file all use `valid_to=None` for the "current" agreement,
  per the prior finding (see `[[octopus-monitoring-pricing-pipeline]]` memory) that
  fixtures coincidentally simplifying away real-world date-range shapes have hidden
  bugs before. The new fixture deliberately uses a non-`None`, degenerate `valid_to`
  to avoid repeating that pattern.

## Out of Scope

- Changing `_sync_comparison_rates()` or `_meter_agreement_pairs()` — both are
  unaffected by this fix, and the spec explicitly does not want them touched.
- Backfilling or correcting the historical agreement data itself (Octopus's data is
  authoritative and out of this codebase's control) — the fix only stops the pipeline
  from repeatedly trying to fetch rates for a range that can never be valid.
- Broader validation of `Agreement` shape elsewhere in the codebase (e.g. at
  ingestion/persistence time) — this spec is scoped to the one call site that makes
  the network call.

## Further Notes

Originally identified and deferred in a prior session's DNS-resilience work
(`chore/dns-resilience-and-session-reuse`), noted there as out-of-scope for that
branch. No GitHub issue existed for it before this spec.

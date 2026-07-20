# Fix URL-encoding bug in rate fetching and make rate-fetch failures non-fatal

## Problem Statement

During the app's first real deployment (Raspberry Pi), it crash-looped
indefinitely: every restart re-ran the full historical consumption backfill,
then crashed again fetching pricing/rate data, forever. The app never reached
its steady-state polling loop and never populated pricing data (`agreement`,
`product`, `product_rate` tables).

Root cause: `RateClient._build_endpoint` (`app/data/octopus/rate.py`) builds
Octopus API request URLs for rate data by raw string concatenation, appending
`period_from`/`period_to` as `datetime.isoformat()` directly into the query
string. Its only encoding attempt, `.replace('+00:00', 'Z')`, special-cases
exact UTC — any other timezone offset (e.g. British Summer Time, `+01:00`,
which is in effect right now) leaves a literal `+` in the query string. Since
`+` means "encoded space" in a URL query string, Octopus's API server parses
`period_to=2024-05-24T00:00:00+01:00` as
`period_to=2024-05-24T00:00:00 01:00` and rejects it with
`{'period_to': ['Enter a valid date/time.']}` (HTTP 400).

Separately, this single failure was fatal to the entire process: the
exception propagates uncaught through `PricingRetriever.refresh()`, and
`main.py`'s startup call to `pricing.refresh()` has no exception handling at
all (unlike the *scheduled* recurring pricing job, which already goes through
`_schedule_refresh_job`'s try/except and the top-level `run_pending_safely`
catch-all). One bad rate lookup — for any reason, not just this encoding bug —
therefore kills the whole app before consumption polling is even registered,
and `docker-compose.yml`'s `restart: unless-stopped` just repeats the same
failure forever.

## Solution

Two independent fixes, found and scoped together in one session:

1. Stop building rate-fetch query strings by hand — use `requests`' `params`
   dict (already supported by `OctopusTransport.get()`) so URL-encoding is
   handled correctly regardless of timezone offset.
2. Make rate-fetch failures non-fatal at every level they can occur: a failed
   lookup for one agreement or one comparison product is logged and skipped,
   not fatal to the others; and the startup pricing sync no longer blocks
   consumption polling from starting if it fails for any reason.

## User Stories

1. As the operator of this app, I want a single rate lookup failure (for any
   reason — a transient Octopus API issue, a malformed query, anything) to be
   logged and skipped, so that one bad product or one bad agreement doesn't
   take down consumption polling for everything else.
2. As the operator of this app, I want rate requests to be correctly
   URL-encoded regardless of the current timezone offset, so that pricing
   sync doesn't systematically fail for roughly half the year (British Summer
   Time).
3. As the operator of this app, I want the app to still start up and begin
   polling consumption even if the initial pricing sync fails entirely, so
   that a pricing-side problem never prevents the core consumption-monitoring
   function of the app from running.

## Implementation Decisions

- **`app/data/octopus/rate.py`** (`RateClient`): `_build_endpoint` is replaced
  by building a `params: Dict[str, Any]` dict (`page_size`, and `period_from`/
  `period_to` only if provided) passed to `OctopusTransport.get()`, instead of
  concatenating them into the URL string, so `requests` handles encoding.
  Per [Guy Lipman's Octopus API guide](https://www.guylipman.com/octopus/api_guide.html)
  (a well-known community reference documenting request-format behavior the
  official docs don't cover), the guide explicitly recommends **always
  converting to UTC and using the `Z` suffix** for `period_from`/`period_to`
  — it warns that supplying a local timezone offset (even one that's
  correctly encoded) can cause inconsistent behavior around DST transitions,
  since the consumption/price endpoints match ranges slightly differently
  (`valid_to >= period_from` and `valid_from < period_to` for price data).
  So the fix is not merely "URL-encode the `+` correctly" but **normalize any
  timezone-aware `period_from`/`period_to` to UTC (`.astimezone(timezone.utc)`)
  before formatting**, so a raw non-`Z` offset is never sent at all — this
  is a more robust fix than encoding alone, and matches the API's own
  documented recommendation. `_get_all_readings`/
  `_get_readings_directly_from_endpoint` pass this `params` dict to
  `OctopusTransport.get()` only for the *first* request to an endpoint;
  Octopus's paginated `next` field returns an already fully-formed absolute
  URL for subsequent pages, so those requests pass no additional params.
- **`app/data/pricing.py`** (`PricingRetriever`):
  - `_sync_own_product_rates`: the per-(meter, agreement) loop body (fetch
    rates + persist) is wrapped in try/except `Exception`. On failure, log a
    warning naming the product code and tariff code, and `continue` to the
    next agreement rather than propagating.
  - `_sync_comparison_rates`: the per-product loop body (tariff-code lookup +
    rate fetch + persist) is wrapped the same way — log a warning naming the
    product code, `continue` to the next product.
  - Both loops get the same treatment (no distinction between the account's
    own agreement and a comparison product) — a confirmed decision from this
    session's design discussion.
- **`app/main.py`**: the startup call `pricing.refresh()` (currently
  unprotected, unlike the scheduled recurring pricing job which already goes
  through `_schedule_refresh_job`'s try/except) is extracted into a small
  named function, e.g. `run_initial_pricing_sync(pricing: PricingRetriever) ->
  None`, mirroring the existing `startup()` helper's shape for testability.
  It wraps the call in try/except `Exception`, logging via
  `logger.exception(...)`, so a startup pricing failure no longer prevents
  `register_jobs`/`register_pricing_job` from running and the app from
  entering its polling loop.
- No ADR — this is a bugfix following an established existing pattern (the
  scheduled job's `_schedule_refresh_job` already does try/except-and-log for
  the recurring case), not a new architectural decision.

## Testing Decisions

- **`tests/test_electricity_rate_seam.py`** (existing seam: mocks HTTP via
  `responses` against `OctopusEnergyAPIClient.get_electricity_rates`, the
  highest available seam — already used by 3 existing tests in this file):
  add a regression test that fetches rates with a non-UTC (`+01:00`, British
  Summer Time) `period_from`/`period_to`, and asserts on the actual outgoing
  request URL (`responses.calls[...].request.url`) that the sent
  `period_from`/`period_to` values are normalized to UTC with a `Z` suffix
  (matching Guy Lipman's guide's documented recommendation) — no raw
  non-`Z` offset appears at all, encoded or otherwise. This locks in both the
  exact bug reproduced live in production and the documented-correct request
  format. Also assert the rates still parse correctly.
- **`tests/test_pricing_retrieval.py`** (existing seam: `PricingRetriever`
  against a real `MariaDBClient` with HTTP mocked via `responses`, following
  the existing `test_refresh_skips_a_product_with_no_published_rate_for_the_
  region_without_crashing` pattern already in this file): add a test where
  one product's rate-fetch endpoint returns an error response and another
  product's succeeds — assert the failing product is skipped (no row
  persisted for it) while the succeeding product's rate is still persisted.
  Mirror this for the account's-own-agreement path in
  `_sync_own_product_rates` with two agreements, one failing.
- **`tests/test_refresh_scheduling.py`** (existing seam: tests `main.py`'s
  `register_jobs`/`register_pricing_job`/`run_pending_safely` functions
  directly against a `Mock(spec=...)` retriever): add a test for the new
  `run_initial_pricing_sync` function — given a `PricingRetriever` whose
  `refresh()` raises, assert it does not propagate.
- No test doubles beyond what's already used in these files (`responses` for
  HTTP, a real `mariadb_client` fixture, `Mock(spec=...)` for retrievers) —
  mocking only at the actual system boundary (Octopus's HTTP API), per this
  repo's existing pattern.

## Out of Scope

- Any change to the retry behaviour in `common/decorator.py`'s `@retry()` — a
  systematic 400 error currently gets retried a few times before failing,
  which is wasteful but not part of this fix's scope.
- Any change to how `run_pending_safely` handles *scheduled* job failures —
  that path already correctly catches and logs (confirmed by existing tests
  in `test_refresh_scheduling.py`); only the *unprotected startup* call is
  being fixed.
- Any broader review of exception handling elsewhere in the app (e.g.
  consumption polling's own resilience) — scoped strictly to the pricing/rate
  path that actually broke in production.

## Further Notes

Found and reproduced live during the first real Pi deployment of
`octopus-monitoring`, immediately after the `chore/consolidate-mariadb-env-config`
chore (PR #394) merged — that chore's config changes are unrelated to and
unaffected by this bug. The Pi deployment test is paused pending this fix, to
be resumed once merged.

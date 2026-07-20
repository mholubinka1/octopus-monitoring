# Issues: bugfix-rate-fetch-url-encoding

> Work complete — PR ready to merge.

## Fix URL-encoding bug in rate-fetch requests (#395)

**Blocked by**: None

**User stories**: 2

### What to build

`RateClient._build_endpoint` (`app/data/octopus/rate.py`) currently builds
Octopus API request URLs for rate data by raw string concatenation, appending
`period_from`/`period_to` as `datetime.isoformat()` directly into the query
string. Its only encoding attempt, `.replace('+00:00', 'Z')`, special-cases
exact UTC — any other timezone offset (e.g. British Summer Time, `+01:00`)
leaves a literal `+` in the query string, which Octopus's API server parses as
a space, rejecting the request with a 400 error.

Per [Guy Lipman's Octopus API guide](https://www.guylipman.com/octopus/api_guide.html)
(a well-known community reference documenting request-format behavior the
official docs don't cover), the recommended fix is not merely to URL-encode
the `+` correctly — the guide explicitly recommends **always converting to
UTC and using the `Z` suffix** for `period_from`/`period_to`, warning that a
local timezone offset (even correctly encoded) can cause inconsistent
behavior around DST transitions. So: normalize any timezone-aware
`period_from`/`period_to` to UTC (`.astimezone(timezone.utc)`) before
formatting, so a raw non-`Z` offset is never sent at all, and pass the
result via a `params` dict to `OctopusTransport.get()` (which already accepts
one) for the first request to each endpoint. Pagination's `next` field is
already a fully-formed absolute URL, so subsequent-page requests pass no
additional params.

### Acceptance criteria

- [ ] `RateClient` no longer builds any part of the query string via raw
      string concatenation.
- [ ] Any timezone-aware `period_from`/`period_to` is normalized to UTC with
      a `Z` suffix before being sent — never a raw non-`Z` offset, matching
      Guy Lipman's guide's documented recommendation.
- [ ] A regression test in `tests/test_electricity_rate_seam.py` fetches
      rates using a non-UTC (`+01:00`) `period_from`/`period_to` and asserts
      the actual outgoing request URL sends the UTC/`Z`-normalized value, and
      that rates still parse correctly.
- [ ] All existing tests in `test_electricity_rate_seam.py`,
      `test_gas_rate_seam.py`, and `test_pricing_retrieval.py` still pass
      unchanged.

---

## Make rate-fetch failures non-fatal to the whole app (#396)

**Blocked by**: None

**User stories**: 1, 3

### What to build

A rate-fetch failure (for any reason) currently crashes the entire app: the
per-agreement and per-product loops in `PricingRetriever`
(`app/data/pricing.py`) propagate any exception all the way up, and
`main.py`'s startup call to `pricing.refresh()` has no exception handling at
all — unlike the *scheduled* recurring pricing job, which already goes
through `_schedule_refresh_job`'s try/except. Wrap the per-(meter, agreement)
loop body in `_sync_own_product_rates` and the per-product loop body in
`_sync_comparison_rates` in try/except `Exception`, logging a warning naming
the product/tariff code and continuing to the next item on failure — same
treatment for both loops, no distinction between the account's own agreement
and a comparison product. Separately, extract `main.py`'s startup
`pricing.refresh()` call into a small named function (mirroring the existing
`startup()` helper), wrapped in try/except with `logger.exception(...)`, so a
startup pricing failure no longer blocks `register_jobs`/
`register_pricing_job` and the app entering its polling loop.

Note: the companion issue (#395) fixes the specific root-cause bug (unencoded
timezone offsets, per
[Guy Lipman's Octopus API guide](https://www.guylipman.com/octopus/api_guide.html))
that triggered this in production. This issue is independent defense-in-depth
so *any* future rate-fetch failure — not just this one — can't take the whole
app down.

### Acceptance criteria

- [ ] `_sync_own_product_rates`: a rate-fetch failure for one agreement is
      logged and skipped; other agreements still sync. Test with two
      agreements, one failing.
- [ ] `_sync_comparison_rates`: a rate-fetch failure for one product is
      logged and skipped; other products still sync. Test with two products,
      one failing.
- [ ] `main.py` has a named, independently-testable function wrapping the
      startup pricing sync; a test asserts it does not propagate when
      `PricingRetriever.refresh()` raises.
- [ ] All existing tests in `test_pricing_retrieval.py` and
      `test_refresh_scheduling.py` still pass unchanged.

---

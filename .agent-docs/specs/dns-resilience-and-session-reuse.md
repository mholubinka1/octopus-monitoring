# Reduce DNS-resolution failure exposure: persistent session reuse + fallback resolver

## Problem Statement

Found live during this session's first real Pi deployment monitoring of
`octopus-monitoring`: intermittent `NameResolutionError` warnings against
`api.octopus.energy`, e.g. `Failed to resolve 'api.octopus.energy' ([Errno -3]
Try again)`. Self-healed every time by the existing `@retry()` decorator
(non-fatal), but frequent enough during a historical backfill to be a real
reliability concern rather than a one-off blip.

Two contributing root causes, confirmed by direct investigation on the
deployed container and Pi host:

1. **`OctopusTransport.get()`** (`app/data/octopus/transport.py`) calls the
   bare, module-level `requests.get(...)` on every single call rather than a
   persistent `requests.Session`. Each such call opens a fresh connection,
   forcing its own DNS lookup + TLS handshake. A historical backfill makes
   hundreds of sequential paginated requests to the same host (observed
   `page=1` through `page=193`+ for gas consumption alone in one run) — so
   this multiplies exposure to any single transient DNS hiccup by roughly the
   same factor, instead of resolving once and reusing a keep-alive connection
   for the whole burst.
2. **No DNS fallback.** Docker's embedded resolver (`127.0.0.11` inside the
   container) forwards external queries to the host's one configured
   nameserver, `192.168.0.50` — almost certainly the LAN's pi-hole box (per
   `pi-desktop`'s own setup docs). There is no second resolver to fall back to
   if that one is ever briefly slow or unresponsive.

Ruled out as the cause: broken DNS/network connectivity in general. `api.
octopus.energy` is genuine dual-stack (IPv4 `54.230.201.x` AWS CloudFront +
IPv6), and 60 rapid manual `getent hosts` lookups from both the container and
the Pi host all succeeded cleanly during the investigation. The failures are
transient/load-related against a single resolver, not a fundamentally broken
path.

## Solution

Two small, independent, complementary changes:

1. `OctopusTransport`: replace the per-call `requests.get(...)` with a
   `requests.Session()` created once and reused for the transport's lifetime.
2. `docker-compose.yml`: add a fallback DNS resolver (Cloudflare `1.1.1.1`)
   alongside the primary (`192.168.0.50`) on the `energy-monitor` service.

## User Stories

1. As the operator of this app, I want a historical backfill to make roughly
   one DNS lookup instead of one *per request* for a burst of calls to the
   same host, so a transient DNS hiccup has far less chance of landing during
   that burst.
2. As the operator of this app, I want the container to have a working
   fallback DNS resolver, so a brief unresponsive spell from the LAN's primary
   resolver doesn't cause a resolution failure at all.
3. As a future maintainer, I want this change provable via the existing test
   suite alone, without needing a live Pi redeployment to confirm it worked.

## Implementation Decisions

- **`OctopusTransport.__init__`**: create `self._session = requests.Session()`
  and set `self._session.auth = (settings.api_key, "")` once here, instead of
  passing `auth=(self._api_key, "")` on every call.
- **`OctopusTransport.get()`**: call `self._session.get(...)` instead of the
  module-level `requests.get(...)`. Everything else about the method (the
  `@retry()` decorator, `REQUEST_TIMEOUT_SECONDS`, `raise_for_http_error`
  handling) stays as-is.
- **Session lifetime = transport lifetime = app process lifetime.**
  `OctopusTransport` is constructed once, in `MonitoringClient.__init__`
  (`app/data/base.py`), and already shared across every retriever —
  including concurrent background job threads spawned by
  `_run_with_backoff_in_background` in `main.py` (`consumption_refresh`,
  `pricing_refresh`, `cost_forecast_refresh` each get their own thread). No
  new locking is needed: `requests.Session`/urllib3's connection pool are
  thread-safe for concurrent use — this is the standard use case session
  reuse is designed for, not a new concurrency risk introduced by this
  change.
- **Stale/dropped reused connections are expected to self-heal via the
  existing `@retry()` decorator** (3 attempts, retries on any exception) —
  urllib3's connection pool evicts a dead pooled connection and opens a fresh
  one on the retried call. No new retry logic needed; call out as a testable
  assumption rather than a code change (see Testing Decisions).
- **Explicitly out of scope, noted so a future reader isn't confused**:
  `KrakenTransport` (`app/data/octopus/kraken.py`) and `AgilePredictClient`
  (`app/data/octopus/agile_predict.py`) have the identical bare-`requests`
  pattern, but are called once per daily refresh cycle rather than hundreds
  of times per backfill — the amplification concern doesn't apply at that
  call volume. Left as-is.
- **`docker-compose.yml`**: add `dns: [192.168.0.50, 1.1.1.1]` to the
  `energy-monitor` service only — `mariadb` makes no external calls and
  doesn't need it. `192.168.0.50` stays listed first/primary (preserves
  whatever LAN-local behavior the pi-hole resolver provides); `1.1.1.1` is
  only consulted if the primary doesn't respond.
- No ADR — this is a reliability hardening change following an established
  pattern (persistent HTTP sessions are standard practice), not a new
  architectural decision.

## Testing Decisions

- **`tests/test_octopus_transport.py`** (existing seam: the `responses`
  library, which mocks at the transport/adapter layer and is compatible with
  a session-based rewrite without needing new test infrastructure):
  - All existing tests should continue to pass unmodified against the
    session-based rewrite — session reuse must not change request/response
    behavior for the happy path or any existing error-handling test.
  - Add a test asserting session reuse itself: e.g. two separate `get()`
    calls should be served by the same `requests.Session` instance (spy on
    `Session.get`, or assert identity of `self._session` is stable across
    calls) rather than asserting anything about actual DNS behavior (not
    observable through `responses` mocking).
  - Add a regression test for the self-healing assumption: simulate a
    connection-level failure on the first attempt (e.g. a `responses` side
    effect raising `ConnectionError`) followed by a successful response on
    retry, and assert the overall `get()` call still succeeds via the
    existing `@retry()` decorator — proving session reuse doesn't break the
    retry path.
- No live Pi redeployment is required to consider this done (explicit
  constraint agreed this session) — re-running a live backfill and confirming
  fewer/no `NameResolutionError` log lines is optional additional
  confirmation, not a gate.
- `docker-compose.yml`'s `dns:` addition has no automated test (compose
  config, not application code) — verify by inspection, or `docker compose
  config`, if desired.

## Out of Scope

- `KrakenTransport` / `AgilePredictClient` session reuse (see Implementation
  Decisions) — same pattern, much lower call volume, left as-is.
- A separate bug found in the same live-monitoring session: a `{'period_from':
  ['Must not be greater than period_to.']}` 400 error in rate-fetching, for an
  agreement whose `valid_from` equals its `valid_to` (a zero-width window).
  Already handled gracefully today by `PricingRetriever`'s existing
  try/except-and-skip around per-agreement rate sync (see
  `bugfix-rate-fetch-url-encoding.md` for the established pattern this
  follows) — not part of this DNS-focused fix. Worth a dedicated fix later if
  it recurs often enough to matter.
- Any change to `@retry()`'s attempt count or backoff timing in
  `common/decorator.py`.
- Driving DNS failures to literal zero — not achievable over a home network,
  and not the agreed acceptance bar (see Further Notes).

## Further Notes

Found live during the same Pi deployment/monitoring session as
`bugfix-cost-forecast-current-agreement-range.md` — both surfaced from the
same live-monitoring window. Agreed acceptance bar: *meaningfully reduce* the
frequency of DNS-caused failures, not eliminate them entirely; must be
testable without a live Pi redeploy.

This document intentionally lives on the `bugfix/cost-forecast-current-
agreement-range` branch alongside the unrelated agreement-bug fix, rather
than its own branch — an explicit, deliberate choice this session because two
agents were working in parallel against one shared working directory. Pick a
proper dedicated branch (e.g. `chore/dns-resilience-and-session-reuse`) when
actually picking this up for implementation.

# Issues: chore-dns-resilience-and-session-reuse

> Work complete — PR ready to merge.

## Persistent HTTP session in OctopusTransport

**GitHub issue**: #427

**Blocked by**: None

**User stories**: 1, 3

### What to build

`OctopusTransport` creates a single `requests.Session` in `__init__` (with
auth set on it once) instead of calling the bare, module-level
`requests.get(...)` on every `get()` call. This means a burst of hundreds of
sequential paginated requests to the same host during a historical backfill
resolves DNS once and reuses a keep-alive connection, instead of paying a
fresh DNS lookup + TLS handshake per request. Everything else about `get()`
(the `@retry()` decorator, `REQUEST_TIMEOUT_SECONDS`, `raise_for_http_error`
handling) stays as-is. `KrakenTransport` and `AgilePredictClient` keep their
existing bare-`requests` pattern — same shape, much lower call volume, left
alone.

### Acceptance criteria

- [x] `OctopusTransport.__init__` creates `self._session = requests.Session()`
      and sets auth on it once, instead of passing `auth=(...)` per call.
- [x] `get()` calls `self._session.get(...)` instead of the module-level
      `requests.get(...)`.
- [x] All existing tests in `tests/test_octopus_transport.py` pass unmodified.
- [x] New test proves the same `Session` instance is reused across multiple
      `get()` calls.
- [x] New regression test: a connection-level failure on the first attempt
      followed by a successful response on retry still succeeds end-to-end,
      proving session reuse doesn't break the existing `@retry()` path.

---

## Fallback DNS resolver for the energy-monitor container

**GitHub issue**: #428

**Blocked by**: None

**User stories**: 2

### What to build

Add a fallback DNS resolver to `docker-compose.yml`'s `energy-monitor`
service only, so a brief unresponsive spell from the LAN's primary resolver
(`192.168.0.50`, the pi-hole box) doesn't cause a resolution failure outright.
`mariadb` makes no external calls and doesn't need it.

### Acceptance criteria

- [x] `energy-monitor` service in `docker-compose.yml` has
      `dns: [192.168.0.50, 1.1.1.1]`, primary listed first.
- [x] `mariadb` service is unchanged (no `dns:` key added).
- [x] `docker compose config` validates the file cleanly.

---

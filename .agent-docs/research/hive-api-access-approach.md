# Hive API Access Approach — Research

> Context: issue #493 in the Wayfinder map restructuring this repo into
> `octopus-app` / `hive-app` / `mariadb`. `hive-app` will be a new headless,
> continuously-polling Python service gathering British Gas Hive smart-home
> data, the same operational shape as this repo's existing Octopus poller.
> This document investigates what that actually requires, since Hive has no
> official public API.

## TL;DR

There is no official Hive API — every integration (Home Assistant's core
`hive` integration included) goes through the same undocumented internal
backend (`beekeeper-uk.hivehome.com`) that the official mobile app uses,
authenticated via **AWS Cognito SRP** (`USER_SRP_AUTH`), the same mechanism
Amazon Cognito user pools use generically — not something Hive built or
documents itself. The current, actively-maintained community library is
[`Pyhass/Pyhiveapi`](https://github.com/Pyhass/Pyhiveapi) (PyPI:
`pyhive-integration`, exposing both async `apyhiveapi` and a generated sync
`pyhiveapi`), which is what Home Assistant's core `hive` integration itself
depends on (`manifest.json`: `requirements: ["pyhive-integration==1.0.9"]`,
`loggers: ["apyhiveapi"]`).

**Auth**: username/password → Cognito SRP handshake → short-lived ID/access
token (assume ~1 hour, silently auto-refreshed at 90% of lifetime) + a
refresh token, with an optional "remembered device" SRP flow to skip repeat
SMS-2FA challenges. If a refresh ultimately fails (e.g. long-idle refresh
token expiry) the library falls back to a full re-login, and if the account
has SMS 2FA and the device isn't remembered, that re-login needs a live SMS
code — a real headless-operation risk, not just a theoretical one.

**Data**: heating (current/target temp, mode, boost, schedule now/next/later),
hot water (mode, boost, state), smart plugs (on/off, power usage), lights,
and sensors (motion, contact, battery, hub/Sense smoke/CO/dog-bark/glass) are
all retrievable — confirmed directly from the library's own entity-mapping
source, not just the README's marketing table.

**Cadence**: 120 seconds is the de facto community-standard poll interval —
it's both the library's own hardcoded default and Home Assistant's config
default, with a UI-enforced floor of 30 seconds. No numeric rate limit is
published by Hive anywhere found in this research; the library defines an
`HTTP_TOO_MANY_REQUESTS = 429` constant but has no dedicated 429 backoff
path, implying the backend can throttle but no documented threshold exists.

**ToS risk**: real but narrow. Hive's own Consumer Terms & Conditions
(April 2026, primary source, quoted in full below) contain exactly one
directly on-point clause — "No reverse engineering... object code" — and a
"domestic use only" clause that limits Hive's liability for commercial use
rather than forbidding it outright. No clause explicitly prohibits
third-party API clients, automated polling, or names Home Assistant/community
libraries. This is a **moderate, unquantified** legal risk (breach-of-contract
exposure, account suspension is Hive's discretionary remedy per general
"suspend/withdraw" clauses, not a specifically documented consequence for
this) rather than a **high, documented** one — but it is not zero, and it is
categorically different from Octopus Energy's situation (a documented,
sanctioned public API) referenced in
`.agent-docs/research/octopus-billing-period-api.md`.

## 1. Auth flow — reverse-engineered, but shared with Home Assistant's own integration

Source: [`Pyhass/Pyhiveapi`](https://github.com/Pyhass/Pyhiveapi) source code,
fetched directly (`src/api/hive_auth_async.py`, `src/session/auth.py`,
`src/api/hive_api.py`), and `home-assistant/core`'s
`homeassistant/components/hive/manifest.json`/`__init__.py`, fetched directly.

**This is not a niche or abandoned library.** Home Assistant's own core `hive`
integration manifest declares `"requirements": ["pyhive-integration==1.0.9"]`
and `"loggers": ["apyhiveapi"]` — i.e. Home Assistant's officially-shipped
Hive integration *is* a thin wrapper around this exact community library, not
an independent reimplementation. `manifest.json` also self-declares
`"iot_class": "cloud_polling"`, confirming there is no push/webhook mechanism
— everything is poll-based.

**Discovery.** `HiveApi.get_login_info()` (`src/api/hive_api.py`) fetches
`https://sso.hivehome.com/` (a public, unauthenticated page — the same login
page a browser hits) and regex-extracts three `window.X = "..."`
JS-assignment variables from its first `<script>` tag:
`HiveSSOPoolId` (Cognito user-pool ID), `HiveSSOPublicCognitoClientId`
(Cognito app-client ID), reused as the region source too. This is how the
library learns which Cognito pool/region/client ID to talk to — scraped from
a public page's inline JS, not hardcoded or documented by Hive.

**Login (`HiveAuthAsync.login`, `src/api/hive_auth_async.py`).** Standard
Cognito `USER_SRP_AUTH` flow using `boto3`'s `cognito-idp` client (dummy
placeholder AWS credentials — SRP auth doesn't need real IAM creds, `boto3`
just requires non-`None` values): compute SRP `A`, call `initiate_auth`,
receive a `PASSWORD_VERIFIER` challenge (salt + server `B` + secret block),
compute the password-verification HMAC via the library's own SRP-math module
(`src/api/srp_crypto.py`, standard RFC 5054-style SRP-6a), and
`respond_to_auth_challenge`. On success, `AuthenticationResult` contains
`IdToken`, `AccessToken`, `RefreshToken`, `ExpiresIn`. If the account has SMS
2FA enabled, the challenge is `SMS_MFA` instead, requiring
`auth.sms_2fa(code, session)` with a live SMS code — this is the standard
consumer path, not something an unattended service can complete on its own
unless 2FA is disabled or the "remembered device" flow (below) applies.

**Device-remembering (`device_login`, `DEVICE_SRP_AUTH`/`DEVICE_PASSWORD_VERIFIER`
challenges).** After a successful login, Cognito can return
`NewDeviceMetadata` (`DeviceGroupKey`/`DeviceKey`), stored by
`_store_auth_result`. On subsequent logins, `auth_params["DEVICE_KEY"]` is
included and a `DEVICE_SRP_AUTH` challenge/response pair authenticates as
that remembered device — this is the mechanism that lets a headless service
skip repeated SMS 2FA challenges after the first interactive login, provided
the device key is persisted. If the device isn't remembered (or Cognito
forgets it), `device_login` raises `HiveInvalidDeviceAuthentication` and the
caller must fall back to full username/password + SMS 2FA login again.

**Token refresh (`SessionAuthMixin.hive_refresh_tokens`, `src/session/auth.py`).**
Tokens are refreshed proactively at `token_created + token_expiry *
_refresh_threshold` (README states this threshold is 90% of the token's
`ExpiresIn` lifetime), using Cognito's `REFRESH_TOKEN_AUTH` flow
(`HiveAuthAsync.refresh_token`), guarded by an `asyncio.Lock` so concurrent
pollers don't race a refresh. If the refresh token itself has expired
(`HiveRefreshTokenExpired`) or fails for another reason
(`HiveFailedToRefreshTokens`), the mixin falls back to `_retry_login()` — a
backoff-retried (`delays=(0, 5, 10)`) full re-login attempt — and only raises
`HiveReauthRequired` up to the caller if that also needs an SMS challenge or
exhausts retries. **This is the concrete unattended-operation risk**: a
service that only ever holds a refresh token (no stored password, or a
password but 2FA enabled with no remembered device) can hit a state where it
needs a human to complete an SMS challenge before it can recover.

**Rate limiting.** `helper/const.py` defines an `HTTP_TOO_MANY_REQUESTS = 429`
constant, confirming Hive's backend is known to be capable of returning 429,
but no code path in `session/polling.py` or `hive_api.py` special-cases 429
with a specific backoff/cool-down — generic `OSError`/`HTTPException`/
`HiveApiError` handling in `get_devices` just marks the poll as failed and
retries on the next scheduled interval. **No documented or numerically
specified rate limit was found anywhere** — not in the library, not in Home
Assistant's docs, not on Hive's own site. This should be treated as "unknown,
not zero," not "safe."

**Base endpoint.** Everything (`get_all`, `get_devices`, `get_products`,
`get_actions`, `set_state`, `set_action`) hits
`https://beekeeper-uk.hivehome.com/1.0/...` with a bearer-style
`authorization: <IdToken>` header — a single internal REST backend, not a
GraphQL API or a separate "integrations" surface the way Octopus Energy
provides (contrast with `.agent-docs/research/octopus-billing-period-api.md`,
where Octopus's Kraken GraphQL API is a first-party, if not fully documented,
product surface). Hive's `beekeeper` backend is the same one the consumer
mobile app itself calls; there is no separate/lower-risk "integrations"
endpoint to prefer instead.

## 2. Data actually retrievable

Source: `Pyhass/Pyhiveapi`'s own `README.md` capability table (fetched
directly) **cross-checked against its source**, since a README can overstate
what code does — `src/helper/const.py`'s `PRODUCTS`/`DEVICES` entity-mapping
dictionaries (which drive what Home Assistant entities actually get created)
and `src/devices/heating.py`'s method list.

| Area | Confirmed retrievable | Source |
| --- | --- | --- |
| Heating | current temperature, target temperature, mode (`SCHEDULE`/`MANUAL`/`OFF`), state, boost on/off + duration/temp, heat-on-demand, min/max range | `PRODUCTS["heating"]`/`["trvcontrol"]` entity configs; `heating.py` methods `get_current_temperature`, `get_target_temperature`, `get_mode`, `get_state`, `get_heat_on_demand`, `minmax_temperature` |
| Heating schedule | now/next/later view of the weekly schedule | `heating.py: get_schedule_now_next_later`, reading `device.data["state"]["schedule"]` — the **raw full weekly schedule already exists in the same API payload** the library parses down to now/next/later; a consumer wanting the full schedule (not just the library's condensed view) can read the same raw field directly |
| Hot water | mode (`schedule`/`on`/`off`), boost on/off, state | `PRODUCTS["hotwater"]` entity configs (`Hotwater_State`, `Hotwater_Mode`, `Hotwater_Boost`) |
| Smart plugs | on/off, live power usage (W), mode, availability | `PRODUCTS["activeplug"]` entity configs (`Power`, `Mode`, `Availability`) |
| Lights | on/off, brightness, colour temperature, RGB, mode, availability | `PRODUCTS["warmwhitelight"/"tuneablelight"/"colourtuneablelight"]` |
| Sensors | motion (+ ambient temperature reading on motion sensors), contact open/close, battery level, online/availability | `PRODUCTS["motionsensor"/"contactsensor"]`, `DEVICES["motionsensor"/"contactsensor"/"thermostatui"/"trv"]` (battery/availability apply to most physical devices, not just sensors) |
| Hub / Sense | smoke/CO detection, dog-bark detection, glass-break detection, hub connectivity | `PRODUCTS["sense"]`, `DEVICES["hub"/"sense"]` |

No energy-consumption-history endpoint (beyond live plug power draw) was
found in this library — `motion_sensor()` in `hive_api.py` hits a
`/products/{type}/{id}/events?from=...&to=...` endpoint for historical
sensor *events* (motion/contact triggers), which could plausibly be reused
for other product types, but this wasn't exercised or confirmed for
plug/heating history within this research; treat "historical energy usage
beyond current instantaneous power" as **unconfirmed**, not "unavailable" —
worth a follow-up spike if `hive-app-data-scope` wants it.

## 3. Polling cadence norms

Source: `Pyhass/Pyhiveapi`'s `src/helper/hivedataclasses.py`
(`_SCAN_INTERVAL = timedelta(seconds=120)`, the library's own hardcoded
default), `home-assistant/core`'s `homeassistant/components/hive/__init__.py`
(`CONF_SCAN_INTERVAL, 120` — Home Assistant's config-entry default,
independently arriving at the same 120s), and the Home Assistant Hive
integration's own docs page (fetched directly): "Scan Interval: Update the
scan interval allowing the integration to poll for data more frequently
(Cannot be set lower than 30 seconds)."

**120 seconds (2 minutes) is the community-standard default**, confirmed
independently at both the library level and the Home Assistant integration
level, with 30 seconds as the documented practical floor (not a
Hive-published limit — a Home Assistant UI-imposed one). No source found
documents what happens if you poll faster than 30s, or states an explicit
requests-per-minute ceiling.

The library's own polling logic (`PollingMixin.update_data`,
`src/session/polling.py`) is itself interval-gated internally
(`self.config.scan_interval`, defaulting to the same 120s) with an
`asyncio.Lock` to prevent concurrent overlapping polls, and a
"slow-poll" detector (`_slow_poll_threshold`) that flags API responses over a
threshold duration and falls back to serving cached entity state rather than
hammering a struggling backend — a self-imposed politeness mechanism, not
one required by any published Hive rate limit.

## 4. Terms-of-Service risk

Source: Hive's own **Consumer Terms & Conditions** PDF, dated **April
2026**, fetched directly from
`https://assets.ctfassets.net/mijf9lz5yt3u/7dqXYOWFkikSnG5A4RNosX/01ccf62251a73af34548fd9938b9bb05/Hive-Terms-and-Conditions-April-2026.pdf`
(linked from hivehome.com's own terms page, extracted with `pdftotext`,
grepped for relevant clauses — full text read, not a secondhand summary),
plus `hivehome.com/acceptable-use` and `hivehome.com/terms` (the general
*website* terms, fetched directly, distinct from the *product/service*
Consumer T&Cs above — this distinction matters and is called out below).

**The one directly on-point clause**, verbatim, from §11 "General legal
terms" of the Consumer Terms & Conditions:

> "No reverse engineering: You must not reverse engineer, decompile, adapt or
> alter the object code for the Services or any Hive product unless
> permitted by law."

This is a real, currently-in-force contractual restriction that a
`pyhiveapi`/`apyhiveapi`-based integration sits in tension with — the
Cognito pool/client IDs are *scraped from a public login page's JS*
(arguably not "decompiling object code" in the traditional binary-reversing
sense) but the resulting client mimics the app's private backend protocol,
which is the behaviour this clause is aimed at. **No source found draws a
bright line between "inspected public JS" and "reverse-engineered the
service"** — this is a genuine grey area, not a resolved one.

**Also relevant but softer** — §8.5 "Domestic use only":

> "We supply products for domestic and private use. If you use products for
> commercial, business or resale purposes, we will have no liability to you
> for any loss of profit, loss of business, business interruption or loss of
> business opportunity."

This is a **liability carve-out, not a usage prohibition** — it doesn't say
commercial/automated use is forbidden, only that Hive won't compensate for
business losses if you do it anyway. Running `hive-app` for personal home
monitoring (the stated use case here) is squarely "domestic and private
use," so this clause is low-relevance to this specific project, but would
become directly relevant if this were ever repackaged/sold to others.

**What was searched for and *not* found**: no clause anywhere in the
Consumer T&Cs, the Acceptable Use Policy, or the general website Terms
explicitly names "API," "automated access," "bots," "scrapers," "robots," or
third-party integrations like Home Assistant. The Acceptable Use Policy's
closest general clause — "Not to access without authority, interfere with,
damage or disrupt: any part of our site; any equipment or network on which
our site is stored; any software used in the provision of our site" — reads
as scoped to the marketing *website*, not explicitly to the app/backend
service, and general enough that its applicability to API polling is
debatable rather than clear-cut. **An earlier AI-generated web-search
summary in this research process claimed hivehome.com explicitly prohibits
"screen scraping" and "automated means" — that claim did NOT survive a
direct fetch-and-read of the actual pages and is retracted here**; it likely
conflated hivehome.com (the smart-home product, owned by Centrica) with an
unrelated same-named company (`hive.com`, a project-management SaaS product)
that does publish that kind of language. This is flagged explicitly because
it's exactly the kind of secondary-source error this research process exists
to catch.

No suspension/termination clause specific to API misuse, reverse engineering,
or automated access was found — the only suspension/termination language in
the Consumer T&Cs is tied to non-payment (§5.4, §7.3) and to Hive's general
right to "suspend or withdraw" the site/service for maintenance or business
reasons (§6, §4.4), not framed as an enforcement mechanism for the
reverse-engineering clause.

**No evidence search was able to confirm actual account suspensions for
API/automation use.** A search across Home Assistant's and `Pyhiveapi`'s
GitHub issue trackers for reports of accounts being banned/locked/suspended
specifically for using these libraries did not surface any — but this is
"not found in a limited search," not "confirmed never happens," and Home
Assistant's Hive integration having existed and worked since HA 0.59 with
continued official maintainer support (`@Rendili`, `@KJonline` — the same
maintainers as `Pyhass/Pyhiveapi`) is circumstantial evidence of tolerance in
practice, not a legal guarantee.

## Recommendation

1. **The technical approach is sound and low-effort**: build `hive-app`'s
   client as a thin wrapper around `pyhive-integration` (`apyhiveapi`)
   rather than reimplementing Cognito SRP from scratch — it's the same
   library Home Assistant's own core integration depends on, actively
   maintained, and already handles the SRP math, token refresh, device
   remembering, and entity-mapping this project would otherwise need to
   build itself.
2. **Plan for the SMS-2FA/device-remembering edge case explicitly** in the
   client/auth design the eventual spec will describe: persist the
   `DeviceGroupKey`/`DeviceKey` from the first interactive login (mirroring
   what Home Assistant's config entry does) so routine token refreshes never
   need a live human, and have an explicit, monitored failure mode (e.g. a
   job-run alert, matching this repo's existing `job_run` pattern noted in
   `.agent-docs/research/agile-forecast-fallback-sources.md`) for the case
   where Cognito forgets the device and a real re-login with SMS is needed —
   don't let that fail silently in a headless service.
3. **Default to a 120-second poll interval**, matching both the library's
   own default and Home Assistant's — this is the de facto safe/normal
   cadence across the entire ecosystem this library serves, not something
   `hive-app` needs to independently discover or justify.
4. **Treat the ToS reverse-engineering clause as a real, accepted risk, not
   a blocker** — this is a personal/household monitoring project (squarely
   "domestic use"), the exact same technical approach Home Assistant's
   official, long-running integration uses in production for a large user
   base, and no evidence of enforcement action against this pattern was
   found. But this is a deliberate risk-acceptance decision (like ADR 0002's
   acceptance of unofficial Agile-forecast hobby services), not a
   risk-free one — it's worth one explicit line in the eventual `hive-app`
   spec or an ADR saying so, the way this repo already documents its other
   accepted third-party-dependency risks, so a future reader doesn't mistake
   silence for "this was checked and found safe."
5. **`hive-app-data-scope` (#494) can treat all of §2's table as in-scope
   from day one** — none of it requires extra API surface beyond what
   `apyhiveapi`'s `get_all()` single call already returns (products, devices,
   actions in one response) — the open question for that ticket is
   prioritisation/storage shape, not availability.

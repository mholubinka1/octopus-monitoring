import asyncio
import logging.config
from datetime import UTC, datetime
from logging import Logger, getLogger
from typing import Any

from apyhiveapi import Hive
from apyhiveapi.helper.hive_exceptions import (
    HiveReauthRequired as ApyHiveReauthRequired,
)

from hive_app.common.config import HiveSettings
from hive_app.common.exceptions import HiveReauthRequired
from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus, HiveAuthState
from hive_app.data.mysql.client import MariaDBClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

_DEVICE_NOT_REMEMBERED_MESSAGE = (
    "Hive's remembered device is no longer recognized by Cognito; a live "
    "SMS 2FA code is needed to recover."
)
_LOGIN_REQUIRES_SMS_MESSAGE = (
    "Hive login requires a live SMS 2FA code; a headless service cannot " "supply one."
)


class HiveApiSource:
    """The real HiveSource implementation: a thin synchronous wrapper
    around apyhiveapi's async Cognito-SRP-authenticated client. Consumers
    (HeatingRetriever, HiveAuthenticator) see only the HiveSource Protocol's
    simple verbs -- none of apyhiveapi's Cognito/SRP/asyncio/device
    internals leak through this boundary.

    apyhiveapi is fully asyncio-based; this codebase is fully synchronous
    (schedule + threading.Thread workers). There's no existing
    async-bridging precedent elsewhere in this repo, so this wraps each
    call in its own asyncio.run() -- a fresh event loop (and fresh Hive/
    aiohttp.ClientSession) per call is unnecessary complexity to avoid at
    this cadence (120s heating polls) and is what aiohttp's ClientSession
    requires anyway, since it's bound to the loop that created it and can't
    be reused across separate asyncio.run() calls.

    Per apyhiveapi's own Testing Decisions (see the spec): this class is not
    unit-tested against a live or mocked Cognito flow -- nothing in this
    repo does that today, and it would mean re-implementing SRP math in
    tests. It's exercised only by construction/wiring; HeatingRetriever and
    HiveAuthenticator are tested against a fake HiveSource instead.
    """

    def __init__(self, settings: HiveSettings, mariadb: MariaDBClient) -> None:
        self._settings = settings
        self._mariadb = mariadb

    # -- HiveSource: auth --

    def read_auth_state(self) -> HiveAuthState | None:
        return self._mariadb.read_hive_auth_state()

    def login(self) -> HiveAuthState:
        return asyncio.run(self._login())

    def resume(self, state: HiveAuthState) -> HiveAuthState:
        return asyncio.run(self._resume(state))

    def persist_auth_state(self, state: HiveAuthState) -> None:
        self._mariadb.write_hive_auth_state(state)

    async def _login(self) -> HiveAuthState:
        hive = self._new_hive()
        await self._establish_session(hive, None)
        return self._auth_state_from_session(hive)

    async def _resume(self, state: HiveAuthState) -> HiveAuthState:
        hive = self._new_hive()
        await self._establish_session(hive, state)
        return self._auth_state_from_session(hive)

    @staticmethod
    async def _establish_session(hive: Hive, state: HiveAuthState | None) -> None:
        """Starts hive's Cognito session: a fresh interactive login if no
        auth state is available, otherwise a resume via token/device
        refresh. Shared by _login/_resume (HiveAuthenticator's startup path)
        and _fetch_heating_status's own self-healing fallback (poll path)
        so this state-is-None branching lives in exactly one place."""
        if state is None:
            logger.info("No persisted Hive auth state -- starting interactive login.")
            await HiveApiSource._start_session(
                hive,
                session_config=None,
                reauth_message=_LOGIN_REQUIRES_SMS_MESSAGE,
            )
        else:
            logger.info(
                "Persisted Hive auth state found -- resuming via token/device "
                "refresh."
            )
            await HiveApiSource._start_session(
                hive,
                session_config=HiveApiSource._resume_config(state),
                reauth_message=_DEVICE_NOT_REMEMBERED_MESSAGE,
            )

    @staticmethod
    async def _start_session(
        hive: Hive, session_config: dict[str, Any] | None, reauth_message: str
    ) -> None:
        """Runs hive.startSession(), translating apyhiveapi's own
        HiveReauthRequired into this repo's own exception type (see
        HiveReauthRequired's docstring) so every caller in this class
        raises/handles one consistent exception rather than duplicating
        this try/except at each call site."""
        try:
            if session_config is None:
                await hive.startSession()
            else:
                await hive.startSession(session_config)
        except ApyHiveReauthRequired as e:
            raise HiveReauthRequired(reauth_message) from e

    def _new_hive(self) -> Hive:
        return Hive(username=self._settings.username, password=self._settings.password)

    @staticmethod
    def _resume_config(state: HiveAuthState) -> dict[str, Any]:
        return {
            # startSession() only performs a full interactive login when no
            # "tokens" key is present in config; with one present (even with
            # empty id/access tokens -- only the refresh token matters here,
            # see HiveSession.startSession/updateTokens) it goes straight to
            # getDevices(), refreshing via REFRESH_TOKEN_AUTH/DEVICE_SRP_AUTH
            # as needed rather than a fresh USER_SRP_AUTH login.
            "tokens": {
                "token": "",  # nosec B105 -- placeholder, not a credential; see comment above
                "refreshToken": state.refresh_token,
                "accessToken": "",  # nosec B105 -- same as "token" above
            },
            "device_data": (state.device_group_key, state.device_key, ""),
        }

    @staticmethod
    def _auth_state_from_session(hive: Hive) -> HiveAuthState:
        return HiveAuthState(
            refresh_token=hive.tokens.tokenData.get("refreshToken", ""),
            device_group_key=hive.auth.device_group_key or "",
            device_key=hive.auth.device_key or "",
            updated_at=datetime.now(UTC),
        )

    # -- HiveSource: heating status --

    def fetch_heating_status(self) -> HeatingStatus:
        return asyncio.run(self._fetch_heating_status())

    async def _fetch_heating_status(self) -> HeatingStatus:
        # Re-establishing the session on every poll (rather than reusing a
        # long-lived Hive instance) can itself rotate the refresh token/
        # device keys via Cognito's REFRESH_TOKEN_AUTH -- so the resulting
        # state is always re-persisted below, not just at startup/resume,
        # or a later restart could resume with tokens Cognito has already
        # superseded.
        state = self._mariadb.read_hive_auth_state()
        # If state is None, no prior HiveAuthenticator.authenticate() run
        # ever succeeded (e.g. it failed at startup). _establish_session
        # falling back to a fresh login in that case -- rather than this
        # method raising -- means each of this job's retry-with-backoff
        # attempts is itself a recovery attempt, instead of a permanent
        # failure loop until the process is restarted.
        hive = self._new_hive()
        await self._establish_session(hive, state)
        # Persisted immediately after the session starts, before the
        # heating.get*() calls below -- if one of those triggers apyhiveapi's
        # own internal 90%-lifetime token auto-refresh mid-poll, that
        # rotation wouldn't be captured until the row is next re-read on the
        # following poll. Negligible in practice (tokens were just minted
        # moments earlier in this same call) and self-heals within one
        # 120-second cycle either way.
        self._mariadb.write_hive_auth_state(self._auth_state_from_session(hive))

        device = self._climate_device(hive)
        current_temp = await hive.heating.getCurrentTemperature(device)
        target_temp = await hive.heating.getTargetTemperature(device)
        mode = await hive.heating.getMode(device)
        heating_state = await hive.heating.getState(device)
        boost_status = await hive.heating.getBoostStatus(device)
        schedule = await hive.heating.getScheduleNowNextLater(device) or {}

        return HeatingStatus(
            polled_at=datetime.now(UTC),
            current_temp=current_temp,
            target_temp=target_temp,
            mode=mode,
            state=heating_state,
            boost_active=boost_status == "ON",
            # getBoostTime() returns the raw device "boost" state value
            # (minutes remaining vs. an absolute timestamp is unconfirmed
            # against a real payload -- see
            # .agent-docs/research/hive-api-access-approach.md, and issue
            # #513's identical "confirm against real data, don't guess"
            # stance for heating-active semantics), so it isn't converted
            # into an absolute end-timestamp here.
            boost_ends_at=None,
            schedule=schedule,
        )

    @staticmethod
    def _climate_device(hive: Hive) -> dict[str, Any]:
        climate_devices = hive.deviceList.get("climate", [])
        if not climate_devices:
            raise RuntimeError(
                "No Hive climate (heating) device found on this account."
            )
        return climate_devices[0]

    def persist_heating_status(self, status: HeatingStatus) -> None:
        self._mariadb.write_heating_status(status)

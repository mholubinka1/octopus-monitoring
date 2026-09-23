import logging.config
from logging import Logger, getLogger
from typing import Protocol

from hive_app.common.exceptions import HiveReauthRequired
from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus, HiveAuthState
from hive_app.data.notify import ReauthNotifier

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class HiveSource(Protocol):
    def fetch_heating_status(self) -> HeatingStatus: ...

    def persist_heating_status(self, status: HeatingStatus) -> None: ...

    def read_auth_state(self) -> HiveAuthState | None: ...

    def login(self) -> HiveAuthState: ...

    def resume(self, state: HiveAuthState) -> HiveAuthState: ...

    def persist_auth_state(self, state: HiveAuthState) -> None: ...


class HeatingRetriever:
    _client: HiveSource
    _notifier: ReauthNotifier | None
    _reauth_notified: bool

    def __init__(
        self, client: HiveSource, notifier: ReauthNotifier | None = None
    ) -> None:
        self._client = client
        self._notifier = notifier
        self._reauth_notified = False

    def refresh(self) -> None:
        try:
            status = self._client.fetch_heating_status()
        except HiveReauthRequired:
            self._notify_reauth_required()
            raise
        self._reauth_notified = False
        self._client.persist_heating_status(status)

    def _notify_reauth_required(self) -> None:
        # Only the first *successful* notification of a reauth incident
        # sets the flag -- every retry attempt and subsequent scheduled run
        # raises the same HiveReauthRequired until someone completes the
        # live SMS login, so without this guard one incident would page
        # repeatedly instead of once (see ADR-0018's "narrowly-scoped, not a
        # general alert channel" framing). refresh() clears the flag on the
        # next successful poll, so a later, distinct incident notifies
        # again. A failed delivery attempt does NOT set the flag, so it is
        # retried on the next failure rather than being permanently
        # suppressed.
        if self._reauth_notified or self._notifier is None:
            return
        try:
            self._notifier.notify_reauth_required()
        except Exception:
            logger.exception(
                "Failed to send Hive re-auth alert; will retry on the next "
                "reauth failure. The original HiveReauthRequired error "
                "still propagates."
            )
            return
        self._reauth_notified = True

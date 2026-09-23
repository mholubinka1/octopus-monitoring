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

    def __init__(
        self, client: HiveSource, notifier: ReauthNotifier | None = None
    ) -> None:
        self._client = client
        self._notifier = notifier

    def refresh(self) -> None:
        try:
            status = self._client.fetch_heating_status()
        except HiveReauthRequired:
            self._notify_reauth_required()
            raise
        self._client.persist_heating_status(status)

    def _notify_reauth_required(self) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier.notify_reauth_required()
        except Exception:
            logger.exception(
                "Failed to send Hive re-auth alert; the original "
                "HiveReauthRequired error still propagates."
            )

import logging.config
from logging import Logger, getLogger

from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.heating import HiveSource

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class HiveAuthenticator:
    """Startup auth branching for a HiveSource: resumes via token/device
    refresh when a hive_auth_state row already exists, otherwise performs a
    full interactive login -- persisting the result either way so a
    subsequent restart can resume. Kept as its own small class (rather than
    folded into main()) so this branching logic stays unit-testable in
    isolation and main() stays thin wiring."""

    _client: HiveSource

    def __init__(self, client: HiveSource) -> None:
        self._client = client

    def authenticate(self) -> None:
        state = self._client.read_auth_state()
        if state is None:
            logger.info("No persisted Hive auth state found; logging in.")
            state = self._client.login()
        else:
            logger.info("Persisted Hive auth state found; resuming via refresh.")
            state = self._client.resume(state)
        self._client.persist_auth_state(state)

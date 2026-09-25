import logging.config
from logging import Logger, getLogger
from typing import Protocol

from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import WeatherObservation

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class WeatherSource(Protocol):
    def fetch_current_observation(self) -> WeatherObservation: ...

    def fetch_current_observation_fallback(self) -> WeatherObservation: ...

    def persist_current_observation(self, observation: WeatherObservation) -> None: ...


class WeatherRetriever:
    _client: WeatherSource

    def __init__(self, client: WeatherSource) -> None:
        self._client = client

    def refresh(self) -> None:
        # Mutual exclusivity is load-bearing, not incidental: the fallback
        # fetch must only ever be reachable via the primary fetch's except
        # branch, never called unconditionally alongside it. Mirrors
        # AgileForecastRetriever.refresh()'s primary/fallback shape.
        try:
            observation = self._client.fetch_current_observation()
        except Exception:
            logger.warning(
                "Weather Underground fetch failed; falling back to Open-Meteo.",
                exc_info=True,
            )
            observation = self._client.fetch_current_observation_fallback()

        self._client.persist_current_observation(observation)
        logger.info(
            f"Weather observation refresh: persisted from {observation.source}."
        )

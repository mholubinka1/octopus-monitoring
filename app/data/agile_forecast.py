import logging.config
from datetime import UTC, datetime
from logging import Logger, getLogger
from typing import Protocol

from common.logging import APP_LOGGER_NAME, config
from data.octopus.model import AgileForecastReading

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class AgileForecastSource(Protocol):
    region_code: str

    def fetch_agile_forecast(self, region: str) -> list[AgileForecastReading]: ...

    def fetch_agile_forecast_fallback(
        self, region: str
    ) -> list[AgileForecastReading]: ...

    def persist_agile_forecast(
        self, region: str, readings: list[AgileForecastReading], fetched_at: datetime
    ) -> None: ...


class AgileForecastRetriever:
    _client: AgileForecastSource

    def __init__(self, client: AgileForecastSource) -> None:
        self._client = client

    def refresh(self, as_of: datetime | None = None) -> None:
        if as_of is None:
            as_of = datetime.now(UTC)

        # Mutual exclusivity is load-bearing, not incidental: the fallback
        # fetch must only ever be reachable via the primary fetch's except
        # branch, never called unconditionally alongside it. agile_forecast
        # has no source column -- upsert-by-(region, period_from) means
        # whichever write happens last for a slot wins, so persisting both
        # sources in the same tick would risk x2r.uk silently clobbering
        # agilepredict.com's numbers for that tick.
        try:
            readings = self._client.fetch_agile_forecast(self._client.region_code)
        except Exception:
            logger.warning(
                "agilepredict.com fetch failed; falling back to x2r.uk.",
                exc_info=True,
            )
            readings = self._client.fetch_agile_forecast_fallback(
                self._client.region_code
            )

        self._client.persist_agile_forecast(self._client.region_code, readings, as_of)
        logger.info(
            f"Agile forecast refresh: {len(readings)} reading(s) persisted for "
            f"region {self._client.region_code}."
        )

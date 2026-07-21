import logging.config
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from logging import Logger, getLogger
from typing import Dict, List, Optional, Protocol, Tuple

from common.logging import APP_LOGGER_NAME, config
from data.consumption import ConsumptionFetchSource
from data.model import ConsumptionSummary, Energy
from data.mysql.client import MariaDBClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

BACKFILL_WINDOW_DAYS = 730


class ConsumptionSummaryRetriever:
    _mariadb: MariaDBClient

    def __init__(self, mariadb: MariaDBClient) -> None:
        self._mariadb = mariadb

    def refresh(self) -> None:
        as_of = datetime.now(timezone.utc).date()
        summaries = self._mariadb.read_consumption_summarization_window(as_of)
        self._mariadb.write_consumption_summary(summaries)
        logger.info(f"Consumption summary refresh: {len(summaries)} day(s) summarized.")


class ConsumptionSummaryBackfillSource(ConsumptionFetchSource, Protocol):
    def persist_consumption_summary(
        self, summaries: List[ConsumptionSummary]
    ) -> None: ...


class ConsumptionSummaryBackfill:
    _client: ConsumptionSummaryBackfillSource

    def __init__(self, client: ConsumptionSummaryBackfillSource) -> None:
        self._client = client

    def run(self, as_of: Optional[datetime] = None) -> None:
        if as_of is None:
            as_of = datetime.now(timezone.utc)
        period_from = as_of - timedelta(days=BACKFILL_WINDOW_DAYS)

        self._client.refresh_meters()
        totals: Dict[Tuple[Energy, date], Decimal] = {}
        for meter in self._client.meters:
            (next_page, consumption) = self._client.fetch_consumption(
                meter, period_from
            )
            while True:
                for point in consumption:
                    key = (meter.energy, point.start.date())
                    totals[key] = totals.get(key, Decimal(0)) + point.est_kwh
                if next_page is None:
                    break
                (next_page, consumption) = self._client.fetch_consumption_page(
                    meter.energy, next_page
                )

        summaries = [
            ConsumptionSummary(energy=energy, date=day, total_kwh=total)
            for (energy, day), total in totals.items()
        ]
        self._client.persist_consumption_summary(summaries)
        logger.info(
            f"Yearly comparison backfill: {len(summaries)} day(s) summarized "
            f"across {len(self._client.meters)} meter(s)."
        )

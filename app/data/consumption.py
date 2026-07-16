import logging.config
from datetime import datetime
from logging import Logger, getLogger
from typing import Dict, List, Optional, Protocol, Tuple

from common.decorator import retry
from common.logging import APP_LOGGER_NAME, config
from data.model import Consumption, Energy
from data.octopus.model import Meter

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class ConsumptionSource(Protocol):
    meters: List[Meter]

    def refresh_meters(self) -> None: ...

    def fetch_consumption(
        self, meter: Meter, period_from: datetime
    ) -> Tuple[Optional[str], List[Consumption]]: ...

    def fetch_consumption_page(
        self, energy: Energy, next_page: str
    ) -> Tuple[Optional[str], List[Consumption]]: ...

    def persist_consumption(
        self, meter: Meter, consumption: List[Consumption]
    ) -> None: ...


class ConsumptionRetriever:
    _client: ConsumptionSource

    _latest_retrieved_date: Dict[Energy, datetime]

    def __init__(self, client: ConsumptionSource) -> None:
        self._client = client
        self._latest_retrieved_date: Dict[Energy, datetime] = {}

    def retrieve(self, period_from: Optional[datetime]) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self.get_meter_consumption(meter, period_from)

    def refresh(self) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self.get_meter_consumption(
                meter,
                self._latest_retrieved_date[meter.energy],
            )

    @retry()
    def get_meter_consumption(
        self,
        meter: Meter,
        period_from: Optional[datetime] = None,
    ) -> None:
        if not period_from:
            period_from = meter.start_date()
        logger.debug(f"Retrieving {meter.energy.name} consumption from {period_from}.")
        (next_page, consumption) = self._client.fetch_consumption(meter, period_from)
        latest_retrieved_date = period_from
        while True:
            if consumption:
                self.write(meter, consumption)
                latest_retrieved_date = max(
                    latest_retrieved_date, max(c.end for c in consumption)
                )
            if next_page is None:
                break
            (
                next_page,
                consumption,
            ) = self._client.fetch_consumption_page(meter.energy, next_page)
        logger.info(
            f"Successfully retrieved consumption from {period_from} to {latest_retrieved_date}"
        )
        self._latest_retrieved_date[meter.energy] = latest_retrieved_date

    def write(self, meter: Meter, consumption: List[Consumption]) -> None:
        _min = min(c.start for c in consumption)
        _max = max(c.end for c in consumption)
        logger.info(
            f"Writing {meter.energy.name} consumption data from {_min} to {_max} to database."
        )

        self._client.persist_consumption(meter, consumption)

import logging.config
from datetime import datetime
from logging import Logger, getLogger
from typing import Dict, List, Optional

from common.logging import APP_LOGGER_NAME, config
from data.base import MonitoringClient
from data.model import Consumption, Energy
from data.octopus.model import Meter

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class ConsumptionRetriever:
    _client: MonitoringClient

    _latest_retrieved_date: Dict[Energy, datetime]

    def __init__(self, client: MonitoringClient) -> None:
        self._client = client
        self._latest_retrieved_date: Dict[Energy, datetime] = {}

    def retrieve_consumption(self, period_from: Optional[datetime]) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self.get_meter_consumption(meter, period_from)
        return

    def retrieve_latest_consumption(self) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self.get_meter_consumption(
                meter,
                self._latest_retrieved_date[meter.energy],
            )
        return

    def get_meter_consumption(
        self,
        meter: Meter,
        period_from: Optional[datetime] = None,
    ) -> None:
        if not period_from:
            period_from = meter.start_date()
        logger.info(f"Retrieving consumption from {period_from}.")
        (next, consumption) = self._client.octopus.get_consumption(meter, period_from)
        self.write(meter, consumption)
        while next is not None:
            (
                next,
                consumption,
            ) = self._client.octopus.get_consumption_directly_from_endpoint(
                meter.energy, next
            )
            self.write(meter, consumption)
        latest_retrieved_date = max(c.end for c in consumption)
        logger.info(
            f"Successfully retrieved consumption from {period_from} to {latest_retrieved_date}"
        )
        self._latest_retrieved_date[meter.energy] = latest_retrieved_date
        return

    def write(self, meter: Meter, consumption: List[Consumption]) -> None:
        _min = min(c.start for c in consumption)
        _max = max(c.end for c in consumption)
        logger.info(f"Writing consumption data from {_min} to {_max} to database.")

        self._client.influx.write_consumption(meter, consumption)
        self._client.mariadb.write_consumption(meter, consumption)
        return

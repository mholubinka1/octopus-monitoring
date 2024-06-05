from datetime import datetime
from typing import Dict, List, Optional

from data.base import MonitoringClient
from data.model import Consumption, Energy
from data.octopus.model import Meter


class ConsumptionRetriever:
    _client: MonitoringClient

    _latest_retrieved_date: Dict[Energy, datetime]

    def __init__(self, client: MonitoringClient) -> None:
        self._client = client
        self._latest_retrieved_date: Dict[Energy, datetime] = {}

    def retrieve_consumption(self) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self.get_meter_consumption(meter)
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
        # //TODO: logging of time here
        if not period_from:
            period_from = meter.start_date()
        (next, consumption) = self._client.octopus.get_consumption(meter, period_from)
        self.write(meter, consumption)
        while next is not None:
            (
                next,
                consumption,
            ) = self._client.octopus.get_consumption_directly_from_endpoint(next)
            self.write(meter, consumption)
        self._latest_retrieved_date[meter.energy] = max(c.end for c in consumption)
        return

    def write(self, meter: Meter, consumption: List[Consumption]) -> None:
        self._client.influx.write_consumption(meter, consumption)

        ##PostgresDB
        return

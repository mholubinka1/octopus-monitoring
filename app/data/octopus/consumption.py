from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from data.model import Consumption, Energy, get_raw_unit, to_estimated_kwh
from data.octopus.model import Electricity, Gas, Meter
from data.octopus.transport import OctopusTransport
from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 100


class ConsumptionReading(BaseModel):
    consumption: Decimal
    interval_start: datetime
    interval_end: datetime


class ConsumptionResponse(BaseModel):
    results: List[ConsumptionReading]
    next: Optional[str] = None


class ConsumptionClient:
    _consumption_funcs: Dict

    def __init__(self, transport: OctopusTransport) -> None:
        self._transport = transport
        self._consumption_funcs: Dict = {
            Energy.electricity: self.get_electricity_consumption,
            Energy.gas: self.get_gas_consumption,
        }

    def get_consumption(
        self, meter: Meter, period_from: datetime, period_to: Optional[datetime] = None
    ) -> Tuple[Optional[str], List[Consumption]]:
        func = self._consumption_funcs[meter.energy]
        value = func(meter, period_from, period_to)
        return value

    def get_electricity_consumption(
        self,
        meter: Electricity,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Tuple[Optional[str], List[Consumption]]:
        api_endpoint = (
            self._transport.base_url
            + f"electricity-meter-points/{meter.mpan}/meters/{meter.serial_number}/consumption/"
        )
        api_endpoint = self.build_api_endpoint_from_params(
            api_endpoint, period_from, period_to, page_size
        )
        return self.get_consumption_directly_from_endpoint(
            Energy.electricity, api_endpoint
        )

    def get_gas_consumption(
        self,
        meter: Gas,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Tuple[Optional[str], List[Consumption]]:
        api_endpoint = (
            self._transport.base_url
            + f"gas-meter-points/{meter.mprn}/meters/{meter.serial_number}/consumption/"
        )
        api_endpoint = self.build_api_endpoint_from_params(
            api_endpoint, period_from, period_to, page_size
        )
        return self.get_consumption_directly_from_endpoint(Energy.gas, api_endpoint)

    def build_api_endpoint_from_params(
        self,
        api_endpoint: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        page_size: int,
    ) -> str:
        api_endpoint += f"?page_size={page_size}"
        if period_from:
            api_endpoint += (
                f"&period_from={period_from.isoformat().replace('+00:00', 'Z')}"
            )
            if period_to:
                api_endpoint += (
                    f"&period_from={period_from.isoformat().replace('+00:00', 'Z')}"
                )
        api_endpoint += "&order_by=period"
        return api_endpoint

    def get_consumption_directly_from_endpoint(
        self,
        energy: Energy,
        api_endpoint: str,
    ) -> Tuple[Optional[str], List[Consumption]]:
        parsed = self._transport.get(
            api_endpoint, ConsumptionResponse, description="fetch consumption"
        )
        consumption = [
            Consumption(
                raw=reading.consumption,
                est_kwh=to_estimated_kwh(energy, reading.consumption),
                unit=get_raw_unit(energy),
                start=reading.interval_start,
                end=reading.interval_end,
            )
            for reading in parsed.results
        ]
        return (parsed.next, consumption)

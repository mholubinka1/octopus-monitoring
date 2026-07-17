import logging.config
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import List, Optional, Tuple

from common.logging import APP_LOGGER_NAME, config
from data.model import Energy
from data.octopus.model import Rate
from data.octopus.transport import OctopusTransport
from pydantic import BaseModel

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

DEFAULT_PAGE_SIZE = 1500

TARIFF_PATH = {
    Energy.electricity: "electricity-tariffs",
    Energy.gas: "gas-tariffs",
}


class RateReading(BaseModel):
    value_inc_vat: Decimal
    valid_from: datetime
    valid_to: Optional[datetime] = None


class RateResponse(BaseModel):
    results: List[RateReading]
    next: Optional[str] = None


class RateClient:
    def __init__(self, transport: OctopusTransport) -> None:
        self._transport = transport

    def get_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime] = None,
        period_to: Optional[datetime] = None,
    ) -> List[Rate]:
        return self._get_rates(
            Energy.electricity, product_code, tariff_code, period_from, period_to
        )

    def get_gas_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime] = None,
        period_to: Optional[datetime] = None,
    ) -> List[Rate]:
        return self._get_rates(
            Energy.gas, product_code, tariff_code, period_from, period_to
        )

    def _get_rates(
        self,
        energy: Energy,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]:
        tariff_path = TARIFF_PATH[energy]
        unit_rates = self._get_all_readings(
            self._endpoint(
                tariff_path, product_code, tariff_code, "standard-unit-rates"
            ),
            period_from,
            period_to,
            f"fetch {energy.name} unit rates",
        )
        standing_charges = self._get_all_readings(
            self._endpoint(tariff_path, product_code, tariff_code, "standing-charges"),
            period_from,
            period_to,
            f"fetch {energy.name} standing charges",
        )
        return self._pair(unit_rates, standing_charges)

    def _endpoint(
        self, tariff_path: str, product_code: str, tariff_code: str, resource: str
    ) -> str:
        return (
            self._transport.base_url
            + f"products/{product_code}/{tariff_path}/{tariff_code}/{resource}/"
        )

    def _get_all_readings(
        self,
        api_endpoint: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        description: str,
    ) -> List[RateReading]:
        readings: List[RateReading] = []
        endpoint: Optional[str] = self._build_endpoint(
            api_endpoint, period_from, period_to
        )
        while endpoint:
            (endpoint, page) = self._get_readings_directly_from_endpoint(
                endpoint, description
            )
            readings.extend(page)
        return readings

    def _build_endpoint(
        self,
        api_endpoint: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> str:
        api_endpoint += f"?page_size={DEFAULT_PAGE_SIZE}"
        if period_from:
            api_endpoint += (
                f"&period_from={period_from.isoformat().replace('+00:00', 'Z')}"
            )
        if period_to:
            api_endpoint += f"&period_to={period_to.isoformat().replace('+00:00', 'Z')}"
        return api_endpoint

    def _get_readings_directly_from_endpoint(
        self, api_endpoint: str, description: str
    ) -> Tuple[Optional[str], List[RateReading]]:
        parsed = self._transport.get(
            api_endpoint, RateResponse, description=description
        )
        return (parsed.next, parsed.results)

    @staticmethod
    def _pair(
        unit_rates: List[RateReading], standing_charges: List[RateReading]
    ) -> List[Rate]:
        rates: List[Rate] = []
        for unit_rate in unit_rates:
            standing_charge = next(
                (
                    sc
                    for sc in standing_charges
                    if sc.valid_from <= unit_rate.valid_from
                    and (sc.valid_to is None or unit_rate.valid_from < sc.valid_to)
                ),
                None,
            )
            if standing_charge is None:
                logger.warning(
                    "No standing charge covers unit rate window starting "
                    f"{unit_rate.valid_from} — skipping."
                )
                continue
            rates.append(
                Rate(
                    valid_from=unit_rate.valid_from,
                    valid_to=unit_rate.valid_to,
                    unit_rate=unit_rate.value_inc_vat,
                    standing_charge=standing_charge.value_inc_vat,
                )
            )
        return rates

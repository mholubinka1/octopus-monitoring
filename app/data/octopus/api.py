import logging.config
import re
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Dict, List, Optional, Tuple

import requests
from common.config import OctopusAPISettings
from common.decorator import retry
from common.exceptions import APIError
from common.logging import APP_LOGGER_NAME, config
from common.utils import is_none_or_whitespace
from data.model import Consumption, Energy, get_raw_unit, to_estimated_kwh
from data.octopus import api_utils
from data.octopus.model import Account, Electricity, Gas, Meter, Product
from pydantic import BaseModel

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30


class ConsumptionReading(BaseModel):
    consumption: Decimal
    interval_start: datetime
    interval_end: datetime


class ConsumptionResponse(BaseModel):
    results: List[ConsumptionReading]
    next: Optional[str] = None


class MeterSerialInfo(BaseModel):
    serial_number: str


class AgreementInfo(BaseModel):
    tariff_code: str
    valid_from: str
    valid_to: Optional[str] = None


class ElectricityMeterPointInfo(BaseModel):
    mpan: str
    meters: List[MeterSerialInfo]
    agreements: Optional[List[AgreementInfo]] = None


class GasMeterPointInfo(BaseModel):
    mprn: str
    meters: List[MeterSerialInfo]
    agreements: Optional[List[AgreementInfo]] = None


class PropertyInfo(BaseModel):
    postcode: str
    address_line_1: str = ""
    address_line_2: str = ""
    address_line_3: str = ""
    town: str = ""
    county: str = ""
    electricity_meter_points: List[ElectricityMeterPointInfo] = []
    gas_meter_points: List[GasMeterPointInfo] = []


class AccountMeterInformationResponse(BaseModel):
    properties: List[PropertyInfo]


class ProductSummary(BaseModel):
    code: str
    display_name: str
    direction: str


class ProductListResponse(BaseModel):
    results: List[ProductSummary]
    next: Optional[str] = None


class ProductDetailResponse(BaseModel):
    single_register_electricity_tariffs: Dict[str, Dict] = {}
    dual_register_electricity_tariffs: Dict[str, Dict] = {}
    single_register_gas_tariffs: Dict[str, Dict] = {}


class OctopusEnergyAPIClient:
    _api_key: str
    _account_number: str
    _base_url: str = "https://api.octopus.energy/v1/"

    _consumption_funcs: Dict

    def __init__(self, settings: OctopusAPISettings) -> None:
        self._api_key = settings.api_key
        self._account_number = settings.account_number

        self._consumption_funcs: Dict = {
            Energy.electricity: self.get_electricity_consumption,
            Energy.gas: self.get_gas_consumption,
        }

    # region Account Information

    @retry()
    def get_account_meter_information(
        self,
    ) -> Tuple[Account, List[Meter]]:
        api_endpoint = self._base_url + f"accounts/{self._account_number}"
        response: Optional[requests.Response] = None
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            parsed = AccountMeterInformationResponse.model_validate(response.json())

            properties = next(iter(parsed.properties), None)
            if properties is None:
                raise APIError("")

            postcode = re.sub(r"\s", "", properties.postcode)

            address_lines = [
                properties.address_line_1.strip(),
                properties.address_line_2.strip(),
                properties.address_line_3.strip(),
                properties.town.strip(),
                properties.county.strip(),
            ]
            account = Account(
                self._account_number,
                ", ".join(
                    [
                        address_line
                        for address_line in address_lines
                        if not is_none_or_whitespace(address_line)
                    ]
                ),
                postcode,
            )

            meters: List[Meter] = []

            if properties.electricity_meter_points:
                meters.append(
                    api_utils.to_electricity_meter(
                        [p.model_dump() for p in properties.electricity_meter_points]
                    )
                )
            if properties.gas_meter_points:
                meters.append(
                    api_utils.to_gas_meter(
                        [p.model_dump() for p in properties.gas_meter_points]
                    )
                )
            return (account, meters)
        except Exception as e:
            if response is not None and response.status_code != 200:
                try:
                    error_body: object = response.json()
                except ValueError:
                    error_body = response.text
                raise APIError(error_body) from e
            raise RuntimeError(
                f"Failed to fetch account/meter information: {e}."
            ) from e

    @retry()
    def get_region_code(self, postcode: str) -> str:
        api_endpoint = self._base_url + "industry/grid-supply-points"
        params = {"postcode": postcode}
        response: Optional[requests.Response] = None
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            response_json = response.json()

            results = response_json.get("results", None)
            return results[0].get("group_id")
        except Exception as e:
            if response is not None and response.status_code != 200:
                try:
                    error_body: object = response.json()
                except ValueError:
                    error_body = response.text
                raise APIError(error_body) from e
            raise RuntimeError(
                f"Failed to fetch region code for {postcode}: {e}."
            ) from e

    # endregion

    # region Pricing

    def get_products(self) -> List[Product]:
        products: List[Product] = []
        api_endpoint: Optional[str] = self._base_url + "products/"
        while api_endpoint:
            (api_endpoint, page) = self.get_products_directly_from_endpoint(
                api_endpoint
            )
            products.extend(page)
        return products

    def get_products_directly_from_endpoint(
        self, api_endpoint: str
    ) -> Tuple[Optional[str], List[Product]]:
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            parsed = ProductListResponse.model_validate(response.json())
            products = [
                Product(
                    product_code=summary.code,
                    display_name=summary.display_name,
                    direction=summary.direction,
                )
                for summary in parsed.results
            ]
            return (parsed.next, products)
        except Exception as e:
            raise APIError(e) from e

    def get_product_region_availability(self, product_code: str, region: str) -> bool:
        api_endpoint = self._base_url + f"products/{product_code}/"
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            parsed = ProductDetailResponse.model_validate(response.json())
            return (
                region in parsed.single_register_electricity_tariffs
                or region in parsed.dual_register_electricity_tariffs
                or region in parsed.single_register_gas_tariffs
            )
        except Exception as e:
            raise APIError(e) from e

    # endregion

    # region Consumption

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
            self._base_url
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
            self._base_url
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
        consumption = []
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            parsed = ConsumptionResponse.model_validate(response.json())
            for reading in parsed.results:
                consumption.append(
                    Consumption(
                        raw=reading.consumption,
                        est_kwh=to_estimated_kwh(energy, reading.consumption),
                        unit=get_raw_unit(energy),
                        start=reading.interval_start,
                        end=reading.interval_end,
                    )
                )
            return (parsed.next, consumption)
        except Exception as e:
            raise APIError(e) from e

    # endregion

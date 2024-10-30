import logging.config
import re
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Dict, List, Optional, Tuple

import data.octopus.api_utils as api_utils
import requests
from common.config import OctopusAPISettings
from common.decorator import retry
from common.exceptions import APIError, ConfigurationError
from common.logging import APP_LOGGER_NAME, config
from common.utils import is_none_or_whitespace
from data.model import Consumption, Energy, get_raw_unit, to_estimated_kwh
from data.octopus.model import Account, Electricity, Gas, Meter

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

DEFAULT_PAGE_SIZE = 100


class OctopusEnergyAPIClient:
    _api_key: str
    _account_number: str
    _base_url: str = "https://api.octopus.energy/v1/"

    _consumption_funcs: Dict

    def __init__(self, settings: OctopusAPISettings) -> None:
        api_key = settings.api_key
        account_number = settings.account_number
        if api_key is None:
            raise ConfigurationError("API Key not set.")
        if account_number is None:
            raise ConfigurationError("Account Number not set.")
        self._api_key = api_key
        self._account_number = account_number

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
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
            )
            response.raise_for_status()
            response_json = response.json()

            properties = next(iter(response_json.get("properties", None)), None)
            if properties is None:
                raise APIError("")

            postcode = re.sub(r"\s", "", properties.get("postcode", None))

            address_lines = [
                properties.get("address_line_1", None).strip(),
                properties.get("address_line_2", None).strip(),
                properties.get("address_line_3", None).strip(),
                properties.get("town", None).strip(),
                properties.get("county", None).strip(),
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

            meters: List[Meter] = list()

            electricity_meter_information = properties.get(
                "electricity_meter_points", None
            )
            gas_meter_information = properties.get("gas_meter_points", None)

            if electricity_meter_information:
                if len(electricity_meter_information) != 0:
                    meters.append(
                        api_utils.to_electricity_meter(electricity_meter_information)
                    )
            if gas_meter_information:
                if len(gas_meter_information) != 0:
                    meters.append(api_utils.to_gas_meter(gas_meter_information))
            return (account, meters)
        except Exception as e:
            if response.status_code != 200:
                response_json = response.json()
                raise APIError(response_json)
            raise Exception(f"Failed to fetch account/meter information: {e}.")

    @retry()
    def get_region_code(self, postcode: str) -> str:
        api_endpoint = self._base_url + "industry/grid-supply-points"
        params = {"postcode": postcode}
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
                params=params,
            )
            response.raise_for_status()
            response_json = response.json()

            results = response_json.get("results", None)
            return results[0].get("group_id")
        except Exception as e:
            if response.status_code != 200:
                response_json = response.json()
                raise APIError(response_json)
            raise Exception(f"Failed to fetch region code for {postcode}: {e}.")

    # endregion

    # region Pricing
    """
    def get_product_information(self, product_code: str):
        api_endpoint = self._base_url + f"products/{product_code}"
        try:
            response = requests.get(
                url=api_endpoint,
            )
            response.raise_for_status()
            response_json = response.json()
            return response_json
        except Exception as e:
            if response.status_code != 200:
                response_json = response.json()
                raise APIError(response_json)
            raise Exception(
                f"Failed to fetch product information for {product_code}: {e}."
            )

    def get_full_price_history(
        self, meters: List[Meter], region_code: str
    ) -> List[Meter]:
        for meter in meters:
            for agreement in meter.agreements:
                agreement = self.get_tariff_price_history(agreement, meter.energy)
                pass

    def get_tariff_price_history(self, agreement: Agreement, fuel: Energy) -> Agreement:
        api_endpoint = self._base_url + f"products/{agreement.product_code}/"
        match fuel:
            case Energy.electricity:
                tariff_api_endpoint = (
                    api_endpoint + f"electricity-tariffs/{agreement.tariff_code}/"
                )
                if agreement.tariff_type == TariffType.economy7:
                    raise NotImplementedError(
                        "Economy7 tariffs are not currently supported."
                    )
                agreement.price_history.extend(
                    self.get_price_history(
                        tariff_api_endpoint, agreement.valid_from, agreement.valid_to
                    )
                )
            case Energy.gas:
                tariff_api_endpoint = (
                    api_endpoint + f"gas-tariffs/{agreement.tariff_code}"
                )
                agreement.price_history.extend(
                    self.get_price_history(
                        tariff_api_endpoint, agreement.valid_from, agreement.valid_to
                    )
                )
        return agreement

    def get_price_history(
        self,
        api_endpoint: str,
        period_from: datetime,
        period_to: Optional[datetime] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> List[Price]:
        unit_rates_endpoint = api_endpoint + "standard-unit-rates/"
        standing_charges_endpoint = api_endpoint + "standing-charges/"
        params: Dict[str, Union[int, str]] = {
            "page_size": page_size,
            "period_from": period_from.isoformat().replace("+00:00", "Z"),
        }
        for endpoint in [unit_rates_endpoint, standing_charges_endpoint]:
            try:
                if period_to:
                    params["period_to"] = period_to.isoformat().replace("+00:00", "Z")
                response = requests.get(
                    url=endpoint,
                    params=params,
                )
                response.raise_for_status()
                response_json = response.json()

            except Exception as e:
                if response.status_code != 200:
                    response_json = response.json()
                    raise APIError(response_json)
                raise Exception(
                    f"Failed to fetch tariff price history from {endpoint}: {e}"
                )
    """

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
        consumption = list()
        try:
            response = requests.get(
                url=api_endpoint,
                auth=(self._api_key, ""),
            )
            response.raise_for_status()
            response_json = response.json()
            for result in response_json["results"]:
                consumption.append(
                    Consumption(
                        raw=Decimal(result["consumption"]),
                        est_kwh=to_estimated_kwh(
                            energy, Decimal(result["consumption"])
                        ),
                        unit=get_raw_unit(energy),
                        start=datetime.fromisoformat(result["interval_start"]),
                        end=datetime.fromisoformat(result["interval_end"]),
                    )
                )
            next = response_json.get("next", None)
            return (next, consumption)
        except Exception as e:
            response_json = response.json()
            raise APIError(e)

    # endregion

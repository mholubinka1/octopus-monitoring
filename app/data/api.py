import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, List, Optional

import requests

from app.common.constants import APP_LOGGER_NAME
from app.common.exceptions import APIError, NullValueError

logger = logging.getLogger(APP_LOGGER_NAME)


def retry(
    stop_after: int = 3, retry_delay: int = 10
) -> Callable[[Callable[..., Optional[Any]]], Callable[..., Any]]:
    def decorator(func: Callable[..., Optional[Any]]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            while attempt < stop_after:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.warning(
                        f"Error attempting to execute {func}: {e}. \nRetrying."
                    )
                    attempt += 1
                    time.sleep(retry_delay)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.critical(
                    f"Error attempting to execute {func}: {e}. \nRetries exhausted."
                )
                raise e

        return wrapper

    return decorator


@dataclass
class EnergyMeter:
    sn: str
    mpan: Optional[str]
    mprn: Optional[str]


class Fuel(Enum):
    DUAL = (0,)
    GAS = (1,)
    ELECTRICITY = (2,)


@dataclass
class Consumption:
    fuel: Fuel
    consumption: float
    start: datetime
    end: datetime


def create_cumulative_consumption(
    consumption_history: List[Consumption], period_from: datetime, period_to: datetime
) -> Consumption:
    if not all(
        discrete_value.fuel == consumption_history[0].fuel
        for discrete_value in consumption_history
    ):
        raise ValueError(
            "Calculation Error: to calculate a cumulative consumption all values must have the same fuel type."
        )
    cumulative_consumption = sum(
        discrete_value.consumption for discrete_value in consumption_history
    )
    start = period_from
    end = period_to
    return Consumption(
        fuel=consumption_history[0].fuel,
        consumption=cumulative_consumption,
        start=start,
        end=end,
    )


class OctopusAPI:
    key: str
    electricity_meter: Optional[EnergyMeter]
    gas_meter: Optional[EnergyMeter]
    fuel: Fuel

    reference_url: str = "https://api.octopus.energy/v1/"

    def __init__(
        self,
        key: Optional[str],
        electricity: Optional[EnergyMeter] = None,
        gas: Optional[EnergyMeter] = None,
    ) -> None:
        if not key:
            raise NullValueError(
                "Configuration Error: application requires an API key."
            )
        if not electricity or gas:
            raise NullValueError(
                "Configuration Error: at least one meter must be present."
            )
        self.key = key
        self.electricity_meter = electricity
        self.gas_meter = gas

        self.tarriff = self.set_fuel_configuration()

    def set_fuel_configuration(self) -> Fuel:
        if not self.electricity_meter:
            return Fuel.GAS
        if not self.gas_meter:
            return Fuel.ELECTRICITY
        return Fuel.DUAL

    def build_parameterised_endpoint(
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

    def get_consumption(
        self,
        period_from: Optional[datetime] = None,
        period_to: Optional[datetime] = None,
        page_size: int = 100,
    ) -> List[Consumption]:
        match self.fuel:
            case Fuel.ELECTRICITY:
                return [
                    self.get_electricity_consumption(period_from, period_to, page_size)
                ]
            case Fuel.GAS:
                return [self.get_gas_consumption(period_from, period_to, page_size)]
            case Fuel.DUAL:
                return self.get_electricity_consumption(
                    period_from, period_to, page_size
                ) + self.get_gas_consumption(period_from, period_to, page_size)
            case _:
                raise NotImplementedError("Unhandled fuel type.")

    def get_cumulative_consumption(
        self,
        period_from: datetime,
        period_to: datetime,
        page_size: int = 100,
    ) -> List[Consumption]:
        match self.fuel:
            case Fuel.ELECTRICITY:
                electricity_consumption = self.get_electricity_consumption(
                    period_from, period_to, page_size
                )
                if len(electricity_consumption == 0):
                    return electricity_consumption
                return [
                    create_cumulative_consumption(
                        electricity_consumption, period_from, period_to
                    )
                ]
            case Fuel.GAS:
                gas_consumption = self.get_gas_consumption(
                    period_from, period_to, page_size
                )
                if len(gas_consumption == 0):
                    return gas_consumption
                return [
                    create_cumulative_consumption(
                        gas_consumption, period_from, period_to
                    )
                ]
            case Fuel.DUAL:
                electricity_consumption = self.get_electricity_consumption(
                    period_from, period_to, page_size
                )
                gas_consumption = self.get_gas_consumption(
                    period_from, period_to, page_size
                )
                if len(electricity_consumption) != 0:
                    electricity_consumption = [
                        create_cumulative_consumption(
                            electricity_consumption, period_from, period_to
                        )
                    ]
                if len(gas_consumption) != 0:
                    gas_consumption = [
                        create_cumulative_consumption(
                            gas_consumption, period_from, period_to
                        )
                    ]
                return electricity_consumption + gas_consumption

    @retry()
    def get_electricity_consumption(
        self,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        page_size: int,
        cumulative: bool = False,
    ) -> List[Consumption]:
        if self.electricity_meter:
            api_endpoint = (
                self.reference_url
                + f"electricity-meter-points/{self.electricity_meter.mpan}/meters/{self.electricity_meter.sn}/consumption/"
            )
            api_endpoint = self.build_parameterised_endpoint(
                api_endpoint, period_from, period_to, page_size
            )
            try:
                return self.get_single_fuel_consumption(api_endpoint, Fuel.ELECTRICITY)
            except Exception as e:
                logger.error(
                    f"Failed to retrieve electricity consumption from {api_endpoint}: {e}"
                )
                return list()
        raise NullValueError("Electricity Meter properties can not be None.")

    @retry()
    def get_gas_consumption(
        self,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
        page_size: int,
    ) -> List[Consumption]:
        if self.gas_meter:
            api_endpoint = (
                self.reference_url
                + f"gas-meter-points/{self.gas_meter.mprn}/meters/{self.gas_meter.sn}/consumption/"
            )
            api_endpoint = self.build_parameterised_endpoint(
                api_endpoint, period_from, period_to, page_size
            )
            try:
                return self.get_single_fuel_consumption(api_endpoint, Fuel.GAS)
            except Exception as e:
                logger.error(
                    f"Failed to retrieve gas consumption from {api_endpoint}: {e}"
                )
                return list()
        raise NullValueError("Gas Meter properties can not be None.")

    def get_single_fuel_consumption(
        self,
        api_endpoint: str,
        fuel: Fuel,
    ) -> List[Consumption]:
        consumption = list()
        try:
            while True:
                response = requests.get(
                    url=api_endpoint,
                    auth=(self.key, ""),
                )
                response.raise_for_status()
                response_json = response.json()
                for result in response_json["results"]:
                    consumption.append(
                        Consumption(
                            fuel=fuel,
                            consumption=result["consumption"],
                            start=datetime.fromisoformat(result["interval_start"]),
                            end=datetime.fromisoformat(result["interval_end"]),
                        )
                    )

                next = response_json["next"]
                if not next:
                    break
                api_endpoint = next
        except Exception:
            response_json = response.json()
            raise APIError(response_json)
        finally:
            return consumption

import logging
import re
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from logging import Logger, getLogger
from typing import List, Optional

from common.exceptions import ArgumentError, NullValueError
from common.logging import APP_LOGGER_NAME, config
from data.model import Energy

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

PRODUCT_CODE_REGEX = "^[A-Z]-[0-9A-Z]+-(?P<product_code>[A-Z0-9-]+)-[A-Z]$"


@dataclass
class Account:
    number: str
    address: str
    postcode: str


@dataclass
class Price:
    energy: Energy
    tariff_code: str
    is_active: bool
    unit_rate: float
    standing_charge: float
    valid_from: datetime
    valid_to: Optional[datetime]


class TariffType(Enum):
    variable = (0,)
    economy7 = (1,)
    agile = (2,)
    fixed = (3,)
    prepay = (4,)


def to_tariff_type(tariff_code: str) -> TariffType:
    if tariff_code.startswith("E-2R"):
        return TariffType.economy7
    if "AGILE" in tariff_code:
        return TariffType.agile
    logger.warning(
        f"Tariff type determination logic is incomplete: {tariff_code} has been tagged as {TariffType.variable}."
    )
    return TariffType.variable


class Agreement:
    product_code: str
    tariff_code: str
    tariff_type: TariffType
    valid_from: datetime
    valid_to: Optional[datetime]
    price_history: List[Price]

    def __init__(
        self, tariff_code: str, valid_from: datetime, valid_to: Optional[datetime]
    ) -> None:
        self.tariff_code = tariff_code
        self.tariff_type = to_tariff_type(tariff_code)

        product_code_match = re.search(PRODUCT_CODE_REGEX, tariff_code)
        if not product_code_match:
            raise NullValueError(f"Agreements must have a product code: {tariff_code}")
        self.product_code = product_code_match.groupdict()["product_code"]
        self.valid_from = valid_from
        self.valid_to = valid_to
        self.price_history: List[Price] = list()


class Meter(ABC, object):
    energy: Energy
    serial_number: str
    agreements: List[Agreement]

    def start_date(self) -> datetime:
        return min(a.valid_from for a in self.agreements)


class Electricity(Meter):
    mpan: str

    def __init__(
        self, mpan: str, serial_number: str, agreements: List[Agreement]
    ) -> None:
        self.energy = Energy.electricity
        self.mpan = mpan
        self.serial_number = serial_number
        # TODO: enable this code to function but just extract consumption data if agreements are missing
        if len(agreements) == 0:
            raise ArgumentError(
                "Meter must contain valid tariff information to extract pricing information."
            )
        self.agreements = agreements


class Gas(Meter):
    mprn: str

    def __init__(
        self, mprn: str, serial_number: str, agreements: List[Agreement]
    ) -> None:
        self.energy = Energy.gas
        self.mprn = mprn
        self.serial_number = serial_number
        # TODO: enable this code to function but just extract consumption data if agreements are missing
        if len(agreements) == 0:
            raise ArgumentError(
                "Meter must contain valid tariff information to extract pricing information."
            )
        self.agreements = agreements

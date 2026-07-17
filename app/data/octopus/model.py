import logging.config
import re
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from common.exceptions import ArgumentError, NullValueError
from common.logging import APP_LOGGER_NAME, config
from data.model import Energy

if TYPE_CHECKING:
    from data.octopus.account import (
        AgreementInfo,
        ElectricityMeterPointInfo,
        GasMeterPointInfo,
    )

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

PRODUCT_CODE_REGEX = "^[A-Z]-[0-9A-Z]+-(?P<product_code>[A-Z0-9-]+)-[A-Z]$"


@dataclass
class Account:
    number: str
    address: str
    postcode: str


@dataclass
class Product:
    product_code: str
    display_name: str
    direction: str


@dataclass
class Price:
    energy: Energy
    tariff_code: str
    is_active: bool
    unit_rate: Decimal
    standing_charge: Decimal
    valid_from: datetime
    valid_to: Optional[datetime]


@dataclass
class Rate:
    valid_from: datetime
    valid_to: Optional[datetime]
    unit_rate: Decimal
    standing_charge: Decimal


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
        self.price_history: List[Price] = []

    @classmethod
    def from_response(cls, info: "AgreementInfo") -> "Agreement":
        tariff_code = info.tariff_code.upper()
        valid_from = datetime.fromisoformat(info.valid_from)
        valid_to = None if not info.valid_to else datetime.fromisoformat(info.valid_to)
        return cls(tariff_code, valid_from, valid_to)


class Meter(ABC):
    energy: Energy
    serial_number: str
    agreements: List[Agreement]

    def start_date(self) -> datetime:
        return min(a.valid_from for a in self.agreements)

    @staticmethod
    def _single_meter_point_serial_number(
        meter_points: List[Any], label: str
    ) -> Tuple[Any, str]:
        if len(meter_points) == 0:
            raise NullValueError(f"No {label} meter points found.")
        if len(meter_points) > 1:
            raise ArgumentError(
                f"This software does not currently handle multiple {label}s."
            )
        meter_point = meter_points[0]
        if len(meter_point.meters) == 0:
            raise NullValueError("Meter Serial Number information not available.")
        if len(meter_point.meters) > 1:
            raise ArgumentError(
                f"This software does not currently handle multiple SNs per {label}."
            )
        return meter_point, meter_point.meters[0].serial_number

    @staticmethod
    def _require_agreements(agreements: List[Agreement]) -> None:
        # Tracked in #387: should extract consumption data even without agreements.
        if len(agreements) == 0:
            raise ArgumentError(
                "Meter must contain valid tariff information to extract pricing information."
            )


class Electricity(Meter):
    mpan: str

    def __init__(
        self, mpan: str, serial_number: str, agreements: List[Agreement]
    ) -> None:
        self.energy = Energy.electricity
        self.mpan = mpan
        self.serial_number = serial_number
        Meter._require_agreements(agreements)
        self.agreements = agreements

    @classmethod
    def from_response(
        cls, meter_points: List["ElectricityMeterPointInfo"]
    ) -> "Electricity":
        meter_point, serial_number = Meter._single_meter_point_serial_number(
            meter_points, "MPAN"
        )
        agreements = [
            Agreement.from_response(a) for a in (meter_point.agreements or [])
        ]
        return cls(
            mpan=meter_point.mpan, serial_number=serial_number, agreements=agreements
        )


class Gas(Meter):
    mprn: str

    def __init__(
        self, mprn: str, serial_number: str, agreements: List[Agreement]
    ) -> None:
        self.energy = Energy.gas
        self.mprn = mprn
        self.serial_number = serial_number
        Meter._require_agreements(agreements)
        self.agreements = agreements

    @classmethod
    def from_response(cls, meter_points: List["GasMeterPointInfo"]) -> "Gas":
        meter_point, serial_number = Meter._single_meter_point_serial_number(
            meter_points, "MPRN"
        )
        agreements = [
            Agreement.from_response(a) for a in (meter_point.agreements or [])
        ]
        return cls(
            mprn=meter_point.mprn, serial_number=serial_number, agreements=agreements
        )

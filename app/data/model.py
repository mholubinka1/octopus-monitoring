from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

VOLUME_CORRECTION = Decimal(1.02264)
AVERAGE_CALORIFIC_VALUE = Decimal(39.5)
TO_KWH_DIVISOR = Decimal(3.6)


class Energy(Enum):
    electricity = 0
    gas = 1


def as_energy_char(energy: Energy) -> str:
    match (energy):
        case Energy.electricity:
            return "E"
        case Energy.gas:
            return "G"


class Unit(Enum):
    kwh = 0
    m3 = 1


@dataclass
class Consumption:
    raw: Decimal
    est_kwh: Decimal
    unit: Unit  # Electricity: kwh, Gas: m^3
    start: datetime
    end: datetime


def get_raw_unit(energy: Energy) -> Unit:
    match (energy):
        case Energy.gas:
            return Unit.m3
        case Energy.electricity:
            return Unit.kwh
        case _:
            raise NotImplementedError(f"Unit unknown for energy of type: {energy}")


def to_estimated_kwh(energy: Energy, raw: Decimal) -> Decimal:
    if energy == Energy.electricity:
        return raw
    if energy == Energy.gas:
        try:
            result = (
                raw * VOLUME_CORRECTION * AVERAGE_CALORIFIC_VALUE
            ) / TO_KWH_DIVISOR
            return result
        except Exception as e:
            raise e

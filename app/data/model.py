from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Energy(Enum):
    dual = 0
    gas = 1
    electricity = 2


@dataclass
class Consumption:
    raw: float  # Electricity: kwh, Gas: m^3
    start: datetime
    end: datetime


def to_estimated_kwh(energy: Energy, raw: float) -> float:
    if energy == Energy.dual:
        raise ValueError("Can not convert dual consumption to kwh.")
    if energy == Energy.electricity:
        return raw

    volume_correction = 1.02264
    average_calorific_value = 39.5
    to_kwh_divisor = 3.6
    return (raw * volume_correction * average_calorific_value) / to_kwh_divisor

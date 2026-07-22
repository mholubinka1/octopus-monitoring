from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby
from typing import List

from data.octopus.model import AgileForecastReading

TILE_SOURCE_WINDOW_DAYS = 7


def project_daily_average_consumption(daily_totals_kwh: List[Decimal]) -> Decimal:
    if not daily_totals_kwh:
        raise ValueError(
            "No elapsed days of consumption to project a future average from."
        )
    return sum(daily_totals_kwh, start=Decimal(0)) / len(daily_totals_kwh)


def tile_forecast_beyond(
    forecast: List[AgileForecastReading], target_end: date
) -> List[AgileForecastReading]:
    if not forecast:
        return []

    by_day = {
        day: list(readings)
        for day, readings in groupby(
            sorted(forecast, key=lambda r: r.period_from),
            key=lambda r: r.period_from.date(),
        )
    }
    real_days = sorted(by_day.keys())
    last_real_day = real_days[-1]
    if target_end <= last_real_day:
        return []

    source_days = real_days[-TILE_SOURCE_WINDOW_DAYS:]

    tiled: List[AgileForecastReading] = []
    day_offset = 1
    while True:
        synthetic_day = last_real_day + timedelta(days=day_offset)
        source_day = source_days[(day_offset - 1) % len(source_days)]
        shift = synthetic_day - source_day
        for reading in by_day[source_day]:
            tiled.append(
                AgileForecastReading(
                    period_from=reading.period_from + shift,
                    period_to=reading.period_to + shift,
                    unit_rate=reading.unit_rate,
                )
            )
        if synthetic_day >= target_end:
            break
        day_offset += 1

    return tiled

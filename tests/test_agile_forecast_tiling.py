from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from data.cost_forecast import tile_forecast_beyond
from data.octopus.model import AgileForecastReading

DAY_1 = date(2026, 7, 22)


def _fourteen_day_forecast() -> List[AgileForecastReading]:
    readings = []
    for day_offset in range(14):
        day = DAY_1 + timedelta(days=day_offset)
        period_from = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        # unit_rate encodes the 1-indexed real day number (1..14) so tiled
        # copies can be traced back to their source day in assertions.
        readings.append(
            AgileForecastReading(
                period_from=period_from,
                period_to=period_from + timedelta(minutes=30),
                unit_rate=Decimal(day_offset + 1),
            )
        )
    return readings


def test_day_fifteen_reuses_day_eights_pattern() -> None:
    tiled = tile_forecast_beyond(
        _fourteen_day_forecast(), target_end=DAY_1 + timedelta(days=14)
    )

    day_15 = DAY_1 + timedelta(days=14)
    day_15_readings = [r for r in tiled if r.period_from.date() == day_15]
    assert len(day_15_readings) == 1
    assert day_15_readings[0].unit_rate == Decimal(8)


def test_day_sixteen_reuses_day_nines_pattern() -> None:
    tiled = tile_forecast_beyond(
        _fourteen_day_forecast(), target_end=DAY_1 + timedelta(days=15)
    )

    day_16 = DAY_1 + timedelta(days=15)
    day_16_readings = [r for r in tiled if r.period_from.date() == day_16]
    assert len(day_16_readings) == 1
    assert day_16_readings[0].unit_rate == Decimal(9)


def test_the_seven_day_cycle_repeats_after_day_twenty_one() -> None:
    tiled = tile_forecast_beyond(
        _fourteen_day_forecast(), target_end=DAY_1 + timedelta(days=21)
    )

    day_22 = DAY_1 + timedelta(days=21)
    day_22_readings = [r for r in tiled if r.period_from.date() == day_22]
    assert len(day_22_readings) == 1
    assert day_22_readings[0].unit_rate == Decimal(8)


def test_time_of_day_is_preserved_only_the_date_shifts() -> None:
    tiled = tile_forecast_beyond(
        _fourteen_day_forecast(), target_end=DAY_1 + timedelta(days=14)
    )

    day_15 = DAY_1 + timedelta(days=14)
    reading = next(r for r in tiled if r.period_from.date() == day_15)
    assert reading.period_from.time() == datetime(2000, 1, 1).time()
    assert reading.period_to == reading.period_from + timedelta(minutes=30)


def test_terminates_for_a_target_end_far_beyond_the_real_forecast() -> None:
    target_end = DAY_1 + timedelta(days=60)

    tiled = tile_forecast_beyond(_fourteen_day_forecast(), target_end=target_end)

    assert len(tiled) > 0
    max_date = max(r.period_from.date() for r in tiled)
    assert max_date >= target_end
    # No runaway generation past the requested end (bounded to at most one
    # extra tiled day beyond target_end, from cycle-length rounding).
    assert max_date < target_end + timedelta(days=7)


def test_a_target_end_within_the_real_forecast_produces_no_tiled_days() -> None:
    tiled = tile_forecast_beyond(
        _fourteen_day_forecast(), target_end=DAY_1 + timedelta(days=10)
    )

    assert not tiled


def test_fewer_than_seven_real_days_cycles_through_whatever_is_available() -> None:
    short_forecast = _fourteen_day_forecast()[:3]  # only 3 real days

    tiled = tile_forecast_beyond(short_forecast, target_end=DAY_1 + timedelta(days=5))

    day_4 = DAY_1 + timedelta(days=3)
    day_4_readings = [r for r in tiled if r.period_from.date() == day_4]
    assert len(day_4_readings) == 1
    # Cycles through all 3 available real days: day 4 reuses day 1's pattern.
    assert day_4_readings[0].unit_rate == Decimal(1)

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from data.mysql.client import MariaDBClient
from data.octopus.model import AgileForecastReading

REGION = "H"


def _reading(period_from: datetime, unit_rate: str) -> AgileForecastReading:
    return AgileForecastReading(
        period_from=period_from,
        period_to=period_from + timedelta(minutes=30),
        unit_rate=Decimal(unit_rate),
    )


def test_returns_readings_for_the_region_from_the_given_moment_onward(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.write_agile_forecast(
        REGION,
        [
            _reading(datetime(2026, 7, 22, 0, 0, tzinfo=UTC), "20.00"),
            _reading(datetime(2026, 7, 22, 0, 30, tzinfo=UTC), "21.00"),
        ],
        fetched_at=datetime(2026, 7, 22, 0, 0, tzinfo=UTC),
    )

    readings = mariadb_client.read_agile_forecast(
        REGION, datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    )

    assert len(readings) == 2
    assert readings[0].period_from == datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    assert readings[0].unit_rate == Decimal("20.00")
    assert readings[1].period_from == datetime(2026, 7, 22, 0, 30, tzinfo=UTC)


def test_excludes_readings_from_a_different_region(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.write_agile_forecast(
        REGION,
        [_reading(datetime(2026, 7, 22, 0, 0, tzinfo=UTC), "20.00")],
        fetched_at=datetime(2026, 7, 22, 0, 0, tzinfo=UTC),
    )
    mariadb_client.write_agile_forecast(
        "K",
        [_reading(datetime(2026, 7, 22, 0, 0, tzinfo=UTC), "99.00")],
        fetched_at=datetime(2026, 7, 22, 0, 0, tzinfo=UTC),
    )

    readings = mariadb_client.read_agile_forecast(
        REGION, datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    )

    assert len(readings) == 1
    assert readings[0].unit_rate == Decimal("20.00")


def test_excludes_readings_before_the_given_moment(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.write_agile_forecast(
        REGION,
        [
            _reading(datetime(2026, 7, 21, 23, 30, tzinfo=UTC), "19.00"),
            _reading(datetime(2026, 7, 22, 0, 0, tzinfo=UTC), "20.00"),
        ],
        fetched_at=datetime(2026, 7, 22, 0, 0, tzinfo=UTC),
    )

    readings = mariadb_client.read_agile_forecast(
        REGION, datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    )

    assert len(readings) == 1
    assert readings[0].unit_rate == Decimal("20.00")


def test_returns_an_empty_list_when_nothing_is_stored_for_the_region(
    mariadb_client: MariaDBClient,
) -> None:
    readings = mariadb_client.read_agile_forecast(
        REGION, datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    )

    assert readings == []

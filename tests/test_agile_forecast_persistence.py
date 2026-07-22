from datetime import datetime, timezone
from decimal import Decimal

from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.model import AgileForecastReading


def test_agile_forecast_readings_are_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    fetched_at = datetime(2026, 7, 22, 4, 15, tzinfo=timezone.utc)
    readings = [
        AgileForecastReading(
            period_from=datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc),
            period_to=datetime(2026, 7, 22, 0, 30, tzinfo=timezone.utc),
            unit_rate=Decimal("21.19"),
        )
    ]

    mariadb_client.write_agile_forecast("H", readings, fetched_at)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.agile_forecast).all()

    assert len(stored) == 1
    assert stored[0].region == "H"
    assert stored[0].period_from == readings[0].period_from.replace(tzinfo=None)
    assert stored[0].period_to == readings[0].period_to.replace(tzinfo=None)
    assert stored[0].forecast_unit_rate == Decimal("21.19")
    assert stored[0].fetched_at == fetched_at.replace(tzinfo=None)


def test_refetching_the_same_period_updates_it_in_place_not_a_duplicate(
    mariadb_client: MariaDBClient,
) -> None:
    period_from = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
    period_to = datetime(2026, 7, 22, 0, 30, tzinfo=timezone.utc)
    mariadb_client.write_agile_forecast(
        "H",
        [AgileForecastReading(period_from, period_to, Decimal("21.19"))],
        datetime(2026, 7, 22, 4, 15, tzinfo=timezone.utc),
    )

    mariadb_client.write_agile_forecast(
        "H",
        [AgileForecastReading(period_from, period_to, Decimal("19.50"))],
        datetime(2026, 7, 22, 10, 15, tzinfo=timezone.utc),
    )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.agile_forecast).all()

    assert len(stored) == 1
    assert stored[0].forecast_unit_rate == Decimal("19.50")

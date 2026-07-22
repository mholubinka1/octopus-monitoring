from datetime import date, datetime, timezone
from decimal import Decimal

from data.model import CostForecast
from data.mysql import model
from data.mysql.client import MariaDBClient


def test_a_cost_forecast_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    forecast = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("42.50"),
        projected_total_cost=Decimal("110.00"),
        computed_at=datetime(2026, 7, 22, 4, 0, tzinfo=timezone.utc),
    )

    mariadb_client.write_cost_forecast(forecast)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 1
    assert stored[0].billing_period_start == date(2026, 7, 6)
    assert stored[0].billing_period_end == date(2026, 8, 6)
    assert stored[0].actual_cost_to_date == Decimal("42.50")
    assert stored[0].projected_total_cost == Decimal("110.00")


def test_each_run_appends_a_new_row_rather_than_overwriting(
    mariadb_client: MariaDBClient,
) -> None:
    first = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("42.50"),
        projected_total_cost=Decimal("110.00"),
        computed_at=datetime(2026, 7, 22, 4, 0, tzinfo=timezone.utc),
    )
    second = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("45.00"),
        projected_total_cost=Decimal("112.00"),
        computed_at=datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc),
    )

    mariadb_client.write_cost_forecast(first)
    mariadb_client.write_cost_forecast(second)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 2

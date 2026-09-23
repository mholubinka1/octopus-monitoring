from datetime import UTC, date, datetime
from decimal import Decimal

from octopus_app.data.model import CostForecast, Energy
from octopus_app.data.mysql import model
from octopus_app.data.mysql.client import MariaDBClient


def test_a_cost_forecast_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    forecast = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("42.50"),
        projected_total_cost=Decimal("110.00"),
        computed_at=datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
        energy=Energy.electricity,
    )

    mariadb_client.write_cost_forecast(forecast)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 1
    assert stored[0].billing_period_start == date(2026, 7, 6)
    assert stored[0].billing_period_end == date(2026, 8, 6)
    assert stored[0].actual_cost_to_date == Decimal("42.50")
    assert stored[0].projected_total_cost == Decimal("110.00")


def test_a_gas_cost_forecast_is_persisted_with_its_own_energy_discriminator(
    mariadb_client: MariaDBClient,
) -> None:
    forecast = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("33.89"),
        projected_total_cost=Decimal("120.00"),
        computed_at=datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
        energy=Energy.gas,
    )

    mariadb_client.write_cost_forecast(forecast)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 1
    assert stored[0].energy == "G"
    assert stored[0].actual_cost_to_date == Decimal("33.89")


def test_each_run_appends_a_new_row_rather_than_overwriting(
    mariadb_client: MariaDBClient,
) -> None:
    first = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("42.50"),
        projected_total_cost=Decimal("110.00"),
        computed_at=datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
        energy=Energy.electricity,
    )
    second = CostForecast(
        billing_period_start=date(2026, 7, 6),
        billing_period_end=date(2026, 8, 6),
        actual_cost_to_date=Decimal("45.00"),
        projected_total_cost=Decimal("112.00"),
        computed_at=datetime(2026, 7, 23, 4, 0, tzinfo=UTC),
        energy=Energy.electricity,
    )

    mariadb_client.write_cost_forecast(first)
    mariadb_client.write_cost_forecast(second)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 2

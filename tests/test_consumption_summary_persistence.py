from datetime import date
from decimal import Decimal

from data.model import ConsumptionSummary, Energy
from data.mysql import model
from data.mysql.client import MariaDBClient


def test_a_consumption_summary_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    summary = ConsumptionSummary(
        energy=Energy.electricity,
        date=date(2026, 1, 15),
        total_kwh=Decimal("12.345"),
    )

    mariadb_client.write_consumption_summary([summary])

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.daily_consumption_summary).all()

    assert len(stored) == 1
    assert stored[0].energy == "E"
    assert stored[0].date == date(2026, 1, 15)
    assert stored[0].total_kwh == Decimal("12.345")


def test_resummarizing_a_day_updates_it_in_place_not_a_duplicate(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.write_consumption_summary(
        [
            ConsumptionSummary(
                energy=Energy.electricity,
                date=date(2026, 1, 15),
                total_kwh=Decimal("12.345"),
            )
        ]
    )

    mariadb_client.write_consumption_summary(
        [
            ConsumptionSummary(
                energy=Energy.electricity,
                date=date(2026, 1, 15),
                total_kwh=Decimal("13.000"),
            )
        ]
    )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.daily_consumption_summary).all()

    assert len(stored) == 1
    assert stored[0].total_kwh == Decimal("13.00000")

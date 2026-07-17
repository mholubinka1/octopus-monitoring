from datetime import datetime
from decimal import Decimal

from data.mysql import sql_models
from data.mysql.client import MariaDBClient


def test_an_agreement_row_round_trips_through_the_schema(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as session:
        session.add(
            sql_models.agreement(
                id="E-VAR-22-11-01",
                energy="E",
                product_code="VAR-22-11-01",
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1),
                valid_to=None,
            )
        )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.agreement).all()

    assert len(stored) == 1
    assert stored[0].id == "E-VAR-22-11-01"
    assert stored[0].energy == "E"
    assert stored[0].product_code == "VAR-22-11-01"
    assert stored[0].tariff_code == "E-1R-VAR-22-11-01-A"
    assert stored[0].valid_from == datetime(2022, 11, 1)
    assert stored[0].valid_to is None


def test_a_product_row_round_trips_through_the_schema(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as session:
        session.add(
            sql_models.product(
                product_code="VAR-22-11-01",
                display_name="Flexible Octopus",
                direction="IMPORT",
            )
        )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product).all()

    assert len(stored) == 1
    assert stored[0].product_code == "VAR-22-11-01"
    assert stored[0].display_name == "Flexible Octopus"
    assert stored[0].direction == "IMPORT"


def test_a_product_rate_row_round_trips_through_the_schema(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as session:
        session.add(
            sql_models.product_rate(
                id="AGILE-24-10-01_H_2026010100",
                product_code="AGILE-24-10-01",
                region="H",
                valid_from=datetime(2026, 1, 1),
                valid_to=datetime(2026, 1, 1, 0, 30),
                unit_rate=Decimal("24.531200"),
                standing_charge=Decimal("48.200100"),
            )
        )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product_rate).all()

    assert len(stored) == 1
    assert stored[0].product_code == "AGILE-24-10-01"
    assert stored[0].region == "H"
    assert stored[0].valid_from == datetime(2026, 1, 1)
    assert stored[0].valid_to == datetime(2026, 1, 1, 0, 30)
    assert stored[0].unit_rate == Decimal("24.531200")
    assert stored[0].standing_charge == Decimal("48.200100")

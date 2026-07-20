from datetime import datetime, timezone

from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.model import Agreement, Electricity


def _make_meter(agreements: list) -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=agreements,
    )


def test_an_agreement_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    meter = _make_meter(
        [
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        ]
    )

    mariadb_client.write_agreement(meter, meter.agreements)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.agreement).all()

    assert len(stored) == 1
    assert stored[0].energy == "E"
    assert stored[0].product_code == "VAR-22-11-01"
    assert stored[0].tariff_code == "E-1R-VAR-22-11-01-A"
    assert stored[0].valid_to is None


def test_resyncing_an_agreement_updates_it_in_place_not_a_duplicate(
    mariadb_client: MariaDBClient,
) -> None:
    valid_from = datetime(2022, 11, 1, tzinfo=timezone.utc)
    meter = _make_meter(
        [
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=valid_from,
                valid_to=None,
            )
        ]
    )
    mariadb_client.write_agreement(meter, meter.agreements)

    superseded_agreement = _make_meter(
        [
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=valid_from,
                valid_to=datetime(2023, 5, 1, tzinfo=timezone.utc),
            )
        ]
    )
    mariadb_client.write_agreement(
        superseded_agreement, superseded_agreement.agreements
    )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.agreement).all()

    assert len(stored) == 1
    assert stored[0].valid_to is not None

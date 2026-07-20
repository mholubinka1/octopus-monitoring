from datetime import datetime, timezone
from decimal import Decimal

from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.model import Rate

PRODUCT_CODE = "AGILE-24-10-01"
REGION = "H"


def _make_rate(
    valid_from: datetime, valid_to: datetime, unit_rate: str, standing_charge: str
) -> Rate:
    return Rate(
        valid_from=valid_from,
        valid_to=valid_to,
        unit_rate=Decimal(unit_rate),
        standing_charge=Decimal(standing_charge),
    )


def test_a_product_rate_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    rate = _make_rate(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
        "24.53",
        "48.20",
    )

    mariadb_client.write_product_rate(PRODUCT_CODE, REGION, [rate])

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.product_rate).all()

    assert len(stored) == 1
    assert stored[0].product_code == PRODUCT_CODE
    assert stored[0].region == REGION
    assert stored[0].unit_rate == Decimal("24.53")
    assert stored[0].standing_charge == Decimal("48.20")


def test_resyncing_a_product_rate_updates_it_in_place_not_a_duplicate(
    mariadb_client: MariaDBClient,
) -> None:
    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_to = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    mariadb_client.write_product_rate(
        PRODUCT_CODE, REGION, [_make_rate(valid_from, valid_to, "24.53", "48.20")]
    )

    mariadb_client.write_product_rate(
        PRODUCT_CODE, REGION, [_make_rate(valid_from, valid_to, "26.10", "48.20")]
    )

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.product_rate).all()

    assert len(stored) == 1
    assert stored[0].unit_rate == Decimal("26.10")


def test_half_hourly_rates_for_the_same_product_are_stored_as_distinct_rows(
    mariadb_client: MariaDBClient,
) -> None:
    rates = [
        _make_rate(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
            "24.53",
            "48.20",
        ),
        _make_rate(
            datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
            "26.10",
            "48.20",
        ),
    ]

    mariadb_client.write_product_rate(PRODUCT_CODE, REGION, rates)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.product_rate).all()

    assert len(stored) == 2

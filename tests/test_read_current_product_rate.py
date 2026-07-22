from datetime import datetime, timezone
from decimal import Decimal

from data.mysql import model
from data.mysql.client import MariaDBClient

PRODUCT_CODE = "VAR-24-10-01"
REGION = "H"


def test_returns_the_rate_valid_at_the_given_moment(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202601010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 7, 1, tzinfo=timezone.utc),
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202607010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
                valid_to=None,
                unit_rate=Decimal("25.00"),
                standing_charge=Decimal("50.00"),
            )
        )

    rate = mariadb_client.read_current_product_rate(
        PRODUCT_CODE, REGION, datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    assert rate is not None
    assert rate.unit_rate == Decimal("25.00")
    assert rate.standing_charge == Decimal("50.00")


def test_returns_the_historical_rate_valid_at_a_past_moment(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202601010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 7, 1, tzinfo=timezone.utc),
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202607010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
                valid_to=None,
                unit_rate=Decimal("25.00"),
                standing_charge=Decimal("50.00"),
            )
        )

    rate = mariadb_client.read_current_product_rate(
        PRODUCT_CODE, REGION, datetime(2026, 3, 1, tzinfo=timezone.utc)
    )

    assert rate is not None
    assert rate.unit_rate == Decimal("20.00")


def test_overlapping_rows_deterministically_prefer_the_most_recently_started(
    mariadb_client: MariaDBClient,
) -> None:
    # Bad-upstream-data defence: two open-ended rows should never both cover
    # the same moment in correct data, but if they did, the result must be
    # deterministic (most-recently-started wins), not whatever order the
    # database happens to return with no ORDER BY.
    with mariadb_client.session_write_scope() as s:
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202601010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202603010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
                valid_to=None,
                unit_rate=Decimal("25.00"),
                standing_charge=Decimal("50.00"),
            )
        )

    rate = mariadb_client.read_current_product_rate(
        PRODUCT_CODE, REGION, datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    assert rate is not None
    assert rate.unit_rate == Decimal("25.00")


def test_returns_none_when_no_rate_covers_the_given_moment(
    mariadb_client: MariaDBClient,
) -> None:
    rate = mariadb_client.read_current_product_rate(
        "NONEXISTENT", REGION, datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    assert rate is None

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from data.mysql import model
from data.mysql.client import MariaDBClient
from sqlalchemy.orm import Session

PRODUCT_CODE = "VAR-24-10-01"
REGION = "H"


def _seed_agreement(
    s: Session, valid_from: datetime, valid_to: Optional[datetime] = None
) -> None:
    s.add(
        model.agreement(
            id=f"E{valid_from.strftime('%Y%m%d%H%M%S')}",
            energy="E",
            product_code=PRODUCT_CODE,
            tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
            valid_from=valid_from,
            valid_to=valid_to,
        )
    )


def _seed_rate(
    s: Session,
    valid_from: datetime,
    valid_to: Optional[datetime],
    unit_rate: str,
    standing_charge: str,
) -> None:
    s.add(
        model.product_rate(
            id=f"{PRODUCT_CODE}_{REGION}_{valid_from.strftime('%Y%m%d%H%M')}",
            product_code=PRODUCT_CODE,
            region=REGION,
            valid_from=valid_from,
            valid_to=valid_to,
            unit_rate=Decimal(unit_rate),
            standing_charge=Decimal(standing_charge),
        )
    )


def _seed_consumption(s: Session, period_from: datetime, est_kwh: str) -> None:
    s.add(
        model.consumption(
            id=f"E{period_from.strftime('%Y%m%d%H%M%S')}",
            energy="E",
            period_from=period_from,
            period_to=period_from,
            raw_value=Decimal(est_kwh),
            unit="kWh",
            est_kwh=Decimal(est_kwh),
        )
    )


def test_two_elapsed_days_with_consumption_on_a_stable_rate(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        _seed_agreement(s, datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_rate(
            s,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            None,
            "20.00",
            "48.00",
        )
        _seed_consumption(s, datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc), "1.0")
        _seed_consumption(s, datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc), "1.0")
        _seed_consumption(s, datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc), "2.0")

    results = mariadb_client.read_elapsed_billing_period_costs(
        datetime(2026, 7, 6, tzinfo=timezone.utc),
        datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    by_date = {r.date: r for r in results}
    assert by_date[date(2026, 7, 6)].total_kwh == Decimal("2.0")
    # (2.0 kWh @ 20.00p) + 48.00p standing charge = 88.00p -> /100 = 0.88 GBP
    assert by_date[date(2026, 7, 6)].day_cost_gbp == Decimal("0.88")
    assert by_date[date(2026, 7, 7)].total_kwh == Decimal("2.0")
    assert by_date[date(2026, 7, 7)].day_cost_gbp == Decimal("0.88")


def test_a_mid_period_rate_change_is_reflected_per_half_hour_not_flattened(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        _seed_agreement(s, datetime(2026, 1, 1, tzinfo=timezone.utc))
        # Old rate covers the first half of the day; a new rate takes over
        # at noon -- both apply to consumption on the same calendar day.
        _seed_rate(
            s,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
            "20.00",
            "48.00",
        )
        _seed_rate(
            s,
            datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
            None,
            "30.00",
            "48.00",
        )
        _seed_consumption(s, datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc), "1.0")
        _seed_consumption(s, datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc), "1.0")

    results = mariadb_client.read_elapsed_billing_period_costs(
        datetime(2026, 7, 6, tzinfo=timezone.utc),
        datetime(2026, 7, 7, tzinfo=timezone.utc),
    )

    by_date = {r.date: r for r in results}
    # (1.0 kWh @ 20.00p) + (1.0 kWh @ 30.00p) + 48.00p standing = 98.00p
    assert by_date[date(2026, 7, 6)].day_cost_gbp == Decimal("0.98")

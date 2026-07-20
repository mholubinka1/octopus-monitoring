from datetime import datetime, timezone
from decimal import Decimal

from data.mysql import model
from data.mysql.client import MariaDBClient
from sqlalchemy import and_, or_


def _compute_total_cost(mariadb_client: MariaDBClient, energy: str) -> Decimal:
    """Actual cost for known fixture data, computed by joining
    consumption to agreement (which product/tariff applied) to
    product_rate (what that product/tariff cost) — proving cost is
    derivable via a simple join, with no pricing logic duplicated in
    application code."""
    c = model.consumption
    a = model.agreement
    pr = model.product_rate

    with mariadb_client.session_read_scope() as session:
        rows = (
            session.query(c.est_kwh, pr.unit_rate, pr.standing_charge)
            .join(
                a,
                and_(
                    a.energy == c.energy,
                    c.period_from >= a.valid_from,
                    or_(a.valid_to.is_(None), c.period_from < a.valid_to),
                ),
            )
            .join(
                pr,
                and_(
                    pr.product_code == a.product_code,
                    c.period_from >= pr.valid_from,
                    or_(pr.valid_to.is_(None), c.period_from < pr.valid_to),
                ),
            )
            .filter(c.energy == energy)
            .all()
        )

    variable_cost = sum(
        (Decimal(str(row.est_kwh)) * row.unit_rate for row in rows), Decimal("0")
    )
    standing_charge = max(row.standing_charge for row in rows)
    return variable_cost + standing_charge


def test_electricity_cost_is_computable_via_a_simple_join(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code="AGILE-24-10-01",
                tariff_code="E-1R-AGILE-24-10-01-H",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
        s.add(
            model.product_rate(
                id="AGILE-24-10-01_H_202601010000",
                product_code="AGILE-24-10-01",
                region="H",
                valid_from=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                valid_to=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.20"),
            )
        )
        s.add(
            model.product_rate(
                id="AGILE-24-10-01_H_202601010030",
                product_code="AGILE-24-10-01",
                region="H",
                valid_from=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                valid_to=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                unit_rate=Decimal("30.00"),
                standing_charge=Decimal("48.20"),
            )
        )
        s.add(
            model.consumption(
                id="E20260101000000",
                energy="E",
                period_from=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("0.5"),
                unit="kWh",
                est_kwh=Decimal("0.5"),
            )
        )
        s.add(
            model.consumption(
                id="E20260101003000",
                energy="E",
                period_from=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                period_to=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                raw_value=Decimal("0.3"),
                unit="kWh",
                est_kwh=Decimal("0.3"),
            )
        )

    total_cost = _compute_total_cost(mariadb_client, "E")

    # (0.5 kWh @ 20.00) + (0.3 kWh @ 30.00) + one standing charge of 48.20
    assert total_cost == Decimal("67.20")


def test_gas_cost_is_computable_via_a_simple_join(
    mariadb_client: MariaDBClient,
) -> None:
    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="G20220101000000",
                energy="G",
                product_code="VAR-22-11-01",
                tariff_code="G-1R-VAR-22-11-01-H",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
        s.add(
            model.product_rate(
                id="VAR-22-11-01_H_202601010000",
                product_code="VAR-22-11-01",
                region="H",
                valid_from=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                valid_to=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
                unit_rate=Decimal("7.00"),
                standing_charge=Decimal("29.11"),
            )
        )
        s.add(
            model.consumption(
                id="G20260101000000",
                energy="G",
                period_from=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
                raw_value=Decimal("10.0"),
                unit="kWh",
                est_kwh=Decimal("10.0"),
            )
        )

    total_cost = _compute_total_cost(mariadb_client, "G")

    # (10.0 kWh @ 7.00) + one standing charge of 29.11
    assert total_cost == Decimal("99.11")

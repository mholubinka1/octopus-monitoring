from datetime import UTC, datetime, timedelta
from decimal import Decimal

from data.model import Consumption, Unit
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.model import Agreement, Electricity, Rate
from data.pruning import DataPruner


def _make_electricity_meter() -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=UTC),
                valid_to=None,
            )
        ],
    )


def _half_hour(start: datetime) -> Consumption:
    return Consumption(
        raw=Decimal("1.0"),
        est_kwh=Decimal("1.0"),
        unit=Unit.kwh,
        start=start,
        end=start + timedelta(minutes=30),
    )


def test_prune_consumption_older_than_deletes_only_rows_before_the_cutoff(
    mariadb_client: MariaDBClient,
) -> None:
    electricity = _make_electricity_meter()
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    old_point = _half_hour(cutoff - timedelta(days=1))
    recent_point = _half_hour(cutoff + timedelta(days=1))
    mariadb_client.write_consumption(electricity, [old_point, recent_point])

    deleted = mariadb_client.prune_consumption_older_than(cutoff)

    assert deleted == 1
    with mariadb_client.session_read_scope() as session:
        remaining = session.query(model.consumption).all()
    assert len(remaining) == 1
    assert remaining[0].period_from == recent_point.start.replace(tzinfo=None)


def test_prune_product_rates_older_than_leaves_open_ended_and_future_rates_untouched(
    mariadb_client: MariaDBClient,
) -> None:
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    expired_rate = Rate(
        valid_from=cutoff - timedelta(days=3),
        valid_to=cutoff - timedelta(days=1),
        unit_rate=Decimal("24.53"),
        standing_charge=Decimal("48.20"),
    )
    open_ended_rate = Rate(
        valid_from=cutoff - timedelta(days=2),
        valid_to=None,
        unit_rate=Decimal("25.00"),
        standing_charge=Decimal("49.00"),
    )
    future_rate = Rate(
        valid_from=cutoff + timedelta(days=1),
        valid_to=cutoff + timedelta(days=2),
        unit_rate=Decimal("26.00"),
        standing_charge=Decimal("50.00"),
    )
    mariadb_client.write_product_rate(
        "VAR-22-11-01", "H", [expired_rate, open_ended_rate, future_rate]
    )

    deleted = mariadb_client.prune_product_rates_older_than(cutoff)

    assert deleted == 1
    with mariadb_client.session_read_scope() as session:
        remaining = {row.unit_rate for row in session.query(model.product_rate).all()}
    assert remaining == {Decimal("25.00"), Decimal("26.00")}


def test_data_pruner_run_deletes_expired_consumption_and_rates_but_never_agreements(
    mariadb_client: MariaDBClient,
) -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    retention_days = 14
    electricity = _make_electricity_meter()
    old_agreement = electricity.agreements[0]
    old_point = _half_hour(as_of - timedelta(days=retention_days, hours=1))
    recent_point = _half_hour(as_of - timedelta(days=1))
    mariadb_client.write_consumption(electricity, [old_point, recent_point])
    mariadb_client.write_agreement(electricity, [old_agreement])
    mariadb_client.write_product_rate(
        "VAR-22-11-01",
        "H",
        [
            Rate(
                valid_from=as_of - timedelta(days=retention_days + 2),
                valid_to=as_of - timedelta(days=retention_days, hours=1),
                unit_rate=Decimal("24.53"),
                standing_charge=Decimal("48.20"),
            )
        ],
    )

    DataPruner(mariadb_client, retention_days).run(as_of)

    with mariadb_client.session_read_scope() as session:
        remaining_consumption = session.query(model.consumption).all()
        remaining_rates = session.query(model.product_rate).all()
        remaining_agreements = session.query(model.agreement).all()

    assert len(remaining_consumption) == 1
    assert remaining_consumption[0].period_from == recent_point.start.replace(
        tzinfo=None
    )
    assert remaining_rates == []
    assert len(remaining_agreements) == 1
    assert remaining_agreements[0].valid_from == old_agreement.valid_from.replace(
        tzinfo=None
    )

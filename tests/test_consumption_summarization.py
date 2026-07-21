from datetime import datetime, timedelta, timezone
from decimal import Decimal

from data.consumption_summary import ConsumptionSummaryRetriever
from data.model import Consumption, Unit
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.model import Agreement, Electricity, Gas


def _make_electricity_meter() -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        ],
    )


def _make_gas_meter() -> Gas:
    return Gas(
        mprn="1234567890",
        serial_number="00B1234567",
        agreements=[
            Agreement(
                tariff_code="G-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        ],
    )


def _half_hour(start: datetime, est_kwh: Decimal) -> Consumption:
    return Consumption(
        raw=est_kwh,
        est_kwh=est_kwh,
        unit=Unit.kwh,
        start=start,
        end=start,
    )


def test_refresh_summarizes_raw_consumption_into_daily_totals_per_energy(
    mariadb_client: MariaDBClient,
) -> None:
    electricity = _make_electricity_meter()
    gas = _make_gas_meter()
    as_of = datetime.now(timezone.utc)

    mariadb_client.write_consumption(
        electricity,
        [
            _half_hour(as_of.replace(hour=0, minute=0), Decimal("1.5")),
            _half_hour(as_of.replace(hour=0, minute=30), Decimal("2.5")),
        ],
    )
    mariadb_client.write_consumption(
        gas,
        [
            _half_hour(as_of.replace(hour=0, minute=0), Decimal("0.75")),
        ],
    )

    ConsumptionSummaryRetriever(mariadb_client).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = {
            (row.energy, row.date): row.total_kwh
            for row in session.query(model.daily_consumption_summary).all()
        }

    assert stored[("E", as_of.date())] == Decimal("4.00000")
    assert stored[("G", as_of.date())] == Decimal("0.75000")


def test_refresh_corrects_a_stale_summary_when_raw_consumption_is_revised(
    mariadb_client: MariaDBClient,
) -> None:
    electricity = _make_electricity_meter()
    as_of = datetime.now(timezone.utc)

    mariadb_client.write_consumption(
        electricity,
        [_half_hour(as_of.replace(hour=0, minute=0), Decimal("1.5"))],
    )
    ConsumptionSummaryRetriever(mariadb_client).refresh()

    # Simulate an upstream Octopus correction: the same half-hour is
    # re-fetched with a revised estimate.
    mariadb_client.write_consumption(
        electricity,
        [_half_hour(as_of.replace(hour=0, minute=0), Decimal("2.0"))],
    )
    ConsumptionSummaryRetriever(mariadb_client).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.daily_consumption_summary).all()

    assert len(stored) == 1
    assert stored[0].total_kwh == Decimal("2.00000")


def test_refresh_summarizes_a_gap_day_older_than_the_trailing_window(
    mariadb_client: MariaDBClient,
) -> None:
    electricity = _make_electricity_meter()
    as_of = datetime.now(timezone.utc)
    old_day = as_of - timedelta(days=20)

    mariadb_client.write_consumption(
        electricity,
        [_half_hour(old_day.replace(hour=0, minute=0), Decimal("3.0"))],
    )

    ConsumptionSummaryRetriever(mariadb_client).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.daily_consumption_summary).all()

    assert len(stored) == 1
    assert stored[0].date == old_day.date()
    assert stored[0].total_kwh == Decimal("3.00000")

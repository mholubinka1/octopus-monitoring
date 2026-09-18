from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import responses
from common.config import OctopusAPISettings
from data.cost_forecast import CostForecastRetriever
from data.local_day import start_of_local_day
from data.model import CostForecast, DailyCostSummary, Energy
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.kraken import BillingPeriodClient, KrakenTransport
from data.octopus.model import (
    AgileForecastReading,
    Agreement,
    BillingPeriod,
    Electricity,
    Gas,
    Meter,
    Rate,
)
from sqlalchemy.orm import Session

GRAPHQL_ENDPOINT = "https://api.octopus.energy/v1/graphql/"
PRODUCT_CODE = "VAR-24-10-01"
GAS_PRODUCT_CODE = "VAR-22-11-01"
REGION = "H"


class _RealCostForecastSource:
    """Real MariaDBClient/BillingPeriodClient underneath -- HTTP calls
    mocked via `responses`, DB is the real SQLite fixture -- with meters
    fixed up front so tests don't need to mock the account meter-information
    endpoint too."""

    def __init__(
        self,
        mariadb: MariaDBClient,
        billing_period_client: BillingPeriodClient,
        meters: list[Meter],
        region_code: str,
    ) -> None:
        self._mariadb = mariadb
        self._billing_period_client = billing_period_client
        self.meters = meters
        self.region_code = region_code

    def refresh_meters(self) -> None:
        pass

    def get_current_billing_period(self) -> BillingPeriod:
        return self._billing_period_client.get_current_billing_period()

    def read_agile_forecast(
        self, region: str, as_of: datetime
    ) -> list[AgileForecastReading]:
        return self._mariadb.read_agile_forecast(region, as_of)

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime, region: str, energy: Energy
    ) -> list[DailyCostSummary]:
        return self._mariadb.read_elapsed_billing_period_costs(
            period_from, period_to, region, energy
        )

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Rate | None:
        return self._mariadb.read_current_product_rate(product_code, region, as_of)

    def persist_cost_forecast(self, forecast: CostForecast) -> None:
        self._mariadb.write_cost_forecast(forecast)


class _MeterDiscoveringCostForecastSource(_RealCostForecastSource):
    """Simulates a gas meter that only becomes visible after
    `refresh_meters()` is called -- e.g. newly added to the account after
    `CostForecastRetriever` was constructed -- so a test can prove
    `refresh_meters()` is actually wired into `refresh()`, not merely
    present as a no-op. Without that call, `self.meters` would stay at
    `initial_meters` (electricity only) for the process lifetime."""

    def __init__(
        self,
        mariadb: MariaDBClient,
        billing_period_client: BillingPeriodClient,
        initial_meters: list[Meter],
        discovered_meters: list[Meter],
        region_code: str,
    ) -> None:
        super().__init__(mariadb, billing_period_client, initial_meters, region_code)
        self._discovered_meters = discovered_meters

    def refresh_meters(self) -> None:
        self.meters = self._discovered_meters


def _seed_complete_day(
    s: Session, day: date, est_kwh_per_slot: str, energy: str = "E"
) -> None:
    # A full 48-slot local day -- the completeness guard requires this for
    # any strictly-past elapsed day to count as real, priced consumption
    # rather than falling through to the zero-consumption gap-fill.
    start = start_of_local_day(day)
    for slot in range(48):
        slot_start = start + timedelta(minutes=30 * slot)
        s.add(
            model.consumption(
                id=f"{energy}{slot_start.strftime('%Y%m%d%H%M%S')}",
                energy=energy,
                period_from=slot_start,
                period_to=slot_start + timedelta(minutes=30),
                raw_value=Decimal(est_kwh_per_slot),
                unit="kWh",
                est_kwh=Decimal(est_kwh_per_slot),
            )
        )


def _make_electricity_meter(
    tariff_code: str = f"E-1R-{PRODUCT_CODE}-{REGION}",
    valid_from: datetime = datetime(2022, 1, 1, tzinfo=UTC),
    valid_to: datetime | None = None,
) -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(tariff_code=tariff_code, valid_from=valid_from, valid_to=valid_to)
        ],
    )


def _make_gas_meter(
    tariff_code: str = f"G-1R-{GAS_PRODUCT_CODE}-{REGION}",
    valid_from: datetime = datetime(2022, 1, 1, tzinfo=UTC),
    valid_to: datetime | None = None,
) -> Gas:
    return Gas(
        mprn="1234567890",
        serial_number="G00A123456",
        agreements=[
            Agreement(tariff_code=tariff_code, valid_from=valid_from, valid_to=valid_to)
        ],
    )


def _mock_billing_period(start: str, end: str, is_fixed: bool = True) -> None:
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"data": {"obtainKrakenToken": {"token": "kraken-jwt-token"}}},
        status=200,
    )
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={
            "data": {
                "account": {
                    "billingOptions": {
                        "currentBillingPeriodStartDate": start,
                        "currentBillingPeriodEndDate": end,
                        "isFixed": is_fixed,
                    }
                }
            }
        },
        status=200,
    )


def _source(mariadb: MariaDBClient, meters: list[Meter]) -> _RealCostForecastSource:
    settings = OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    return _RealCostForecastSource(
        mariadb,
        BillingPeriodClient(settings, KrakenTransport()),
        meters,
        REGION,
    )


def _seed_electricity_and_gas_fixtures(s: Session) -> None:
    s.add(
        model.agreement(
            id="E20220101000000",
            energy="E",
            product_code=PRODUCT_CODE,
            tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
            valid_from=datetime(2022, 1, 1, tzinfo=UTC),
            valid_to=None,
        )
    )
    s.add(
        model.product_rate(
            id=f"{PRODUCT_CODE}_{REGION}_202601010000",
            product_code=PRODUCT_CODE,
            region=REGION,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            unit_rate=Decimal("20.00"),
            standing_charge=Decimal("48.00"),
        )
    )
    _seed_complete_day(s, date(2026, 7, 6), "0.1", energy="E")

    s.add(
        model.agreement(
            id="G20220101000000",
            energy="G",
            product_code=GAS_PRODUCT_CODE,
            tariff_code=f"G-1R-{GAS_PRODUCT_CODE}-{REGION}",
            valid_from=datetime(2022, 1, 1, tzinfo=UTC),
            valid_to=None,
        )
    )
    s.add(
        model.product_rate(
            id=f"{GAS_PRODUCT_CODE}_{REGION}_202601010000",
            product_code=GAS_PRODUCT_CODE,
            region=REGION,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            unit_rate=Decimal("7.00"),
            standing_charge=Decimal("29.00"),
        )
    )
    # One elapsed day (2026-07-06), a full 48-slot day totalling 48.0 kWh.
    _seed_complete_day(s, date(2026, 7, 6), "1.0", energy="G")


@responses.activate
def test_gas_actual_cost_is_computed_and_written_as_its_own_energy_row(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-07", "2026-08-07")

    with mariadb_client.session_write_scope() as s:
        _seed_electricity_and_gas_fixtures(s)

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter(), _make_gas_meter()])
    )
    retriever.refresh(as_of=start_of_local_day(date(2026, 7, 7)))

    with mariadb_client.session_read_scope() as session:
        gas_row = session.query(model.cost_forecast).filter_by(energy="G").one()
        electricity_row = session.query(model.cost_forecast).filter_by(energy="E").one()

    # 48 slots * 1.0 kWh/slot = 48.0 kWh @ 7.00p + 29.00p standing =
    # 336.00p + 29.00p = 365.00p -> £3.65
    assert gas_row.actual_cost_to_date == Decimal("3.65")
    # (4.8 kWh @ 20.00p) + 48.00p standing charge = 144.00p -> £1.44,
    # unaffected by gas now also being computed.
    assert electricity_row.actual_cost_to_date == Decimal("1.44")


@responses.activate
def test_gas_projected_total_cost_uses_the_same_average_consumption_formula_as_electricity(
    mariadb_client: MariaDBClient,
) -> None:
    # Gas has no Agile tariff, so its projection must go through the exact
    # same average-recent-consumption, non-Agile formula electricity already
    # uses -- mirrors test_fixed_tariff_actual_cost_and_projection's
    # arithmetic (in test_cost_forecast_retriever.py), but for a gas
    # meter/tariff. Electricity fixtures are the minimal shape needed to
    # satisfy refresh()'s hard electricity requirement; the assertions below
    # are all about the gas row.
    _mock_billing_period("2026-07-07", "2026-08-07")

    with mariadb_client.session_write_scope() as s:
        _seed_electricity_and_gas_fixtures(s)

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter(), _make_gas_meter()])
    )
    retriever.refresh(as_of=start_of_local_day(date(2026, 7, 7)))

    with mariadb_client.session_read_scope() as session:
        gas_row = session.query(model.cost_forecast).filter_by(energy="G").one()

    # (48.0 kWh @ 7.00p) + 29.00p standing charge = 365.00p -> £3.65
    assert gas_row.actual_cost_to_date == Decimal("3.65")
    # total_period_days = Jul6..Aug6 inclusive = 32; remaining_days = 32 - 1
    # elapsed day (Jul6) = 31, at 48.0 kWh/day average, same 7.00p rate +
    # 29.00p standing charge/day -- identical formula to the electricity
    # case in test_fixed_tariff_actual_cost_and_projection.
    remaining_days = 31
    expected_remaining = (
        remaining_days * (Decimal("48.0") * Decimal("7.00") + Decimal("29.00")) / 100
    )
    assert (
        gas_row.projected_total_cost == gas_row.actual_cost_to_date + expected_remaining
    )


@responses.activate
def test_a_gas_meter_added_after_construction_is_picked_up_via_refresh_meters(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-07", "2026-08-07")

    with mariadb_client.session_write_scope() as s:
        _seed_electricity_and_gas_fixtures(s)

    settings = OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    source = _MeterDiscoveringCostForecastSource(
        mariadb_client,
        BillingPeriodClient(settings, KrakenTransport()),
        initial_meters=[_make_electricity_meter()],
        discovered_meters=[_make_electricity_meter(), _make_gas_meter()],
        region_code=REGION,
    )

    retriever = CostForecastRetriever(source)
    retriever.refresh(as_of=start_of_local_day(date(2026, 7, 7)))

    with mariadb_client.session_read_scope() as session:
        energies = {row.energy for row in session.query(model.cost_forecast).all()}

    # If refresh() failed to call refresh_meters() first, self.meters would
    # stay at initial_meters (electricity only) and this would be {"E"}.
    assert energies == {"E", "G"}

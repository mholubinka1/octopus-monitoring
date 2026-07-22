from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import pytest
import responses
from common.config import OctopusAPISettings
from common.exceptions import APIError
from data.cost_forecast import CostForecastRetriever
from data.model import CostForecast, DailyCostSummary
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.agile_predict import AgilePredictClient
from data.octopus.kraken import BillingPeriodClient, KrakenTransport
from data.octopus.model import (
    AgileForecastReading,
    Agreement,
    BillingPeriod,
    Electricity,
    Meter,
    Rate,
)
from sqlalchemy.orm import Session

GRAPHQL_ENDPOINT = "https://api.octopus.energy/v1/graphql/"
AGILE_ENDPOINT = "https://agilepredict.com/api/H/"
PRODUCT_CODE = "VAR-24-10-01"
REGION = "H"


class _RealCostForecastSource:
    """Real MariaDBClient/BillingPeriodClient/AgilePredictClient underneath
    -- HTTP calls mocked via `responses`, DB is the real SQLite fixture --
    with meters fixed up front so tests don't need to mock the account
    meter-information endpoint too."""

    def __init__(
        self,
        mariadb: MariaDBClient,
        billing_period_client: BillingPeriodClient,
        agile_predict_client: AgilePredictClient,
        meters: List[Meter],
        region_code: str,
    ) -> None:
        self._mariadb = mariadb
        self._billing_period_client = billing_period_client
        self._agile_predict_client = agile_predict_client
        self.meters = meters
        self.region_code = region_code

    def refresh_meters(self) -> None:
        pass

    def get_current_billing_period(self) -> BillingPeriod:
        return self._billing_period_client.get_current_billing_period()

    def fetch_agile_forecast(self, region: str) -> List[AgileForecastReading]:
        return self._agile_predict_client.get_forecast(region)

    def persist_agile_forecast(
        self,
        region: str,
        readings: List[AgileForecastReading],
        fetched_at: datetime,
    ) -> None:
        self._mariadb.write_agile_forecast(region, readings, fetched_at)

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime, region: str
    ) -> List[DailyCostSummary]:
        return self._mariadb.read_elapsed_billing_period_costs(
            period_from, period_to, region
        )

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Optional[Rate]:
        return self._mariadb.read_current_product_rate(product_code, region, as_of)

    def persist_cost_forecast(self, forecast: CostForecast) -> None:
        self._mariadb.write_cost_forecast(forecast)


def _make_electricity_meter(
    tariff_code: str = f"E-1R-{PRODUCT_CODE}-{REGION}",
    valid_to: Optional[datetime] = None,
) -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code=tariff_code,
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=valid_to,
            )
        ],
    )


AGILE_PRODUCT_CODE = "AGILE-24-10-01"


def _mock_agile_forecast(prices: List[dict]) -> None:
    responses.add(
        responses.GET,
        AGILE_ENDPOINT,
        json=[
            {
                "name": "Region | H",
                "created_at": "2026-07-06T04:15:00+01:00",
                "prices": prices,
            }
        ],
        status=200,
    )


def _flat_agile_prices(start_day: date, num_days: int, pred: str) -> List[dict]:
    start = datetime(
        start_day.year, start_day.month, start_day.day, tzinfo=timezone.utc
    )
    return [
        {
            "date_time": (start + timedelta(minutes=30 * slot)).isoformat(),
            "agile_pred": pred,
            "agile_low": pred,
            "agile_high": pred,
        }
        for slot in range(48 * num_days)
    ]


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


def _source(mariadb: MariaDBClient, meters: List[Meter]) -> _RealCostForecastSource:
    settings = OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    return _RealCostForecastSource(
        mariadb,
        BillingPeriodClient(settings, KrakenTransport()),
        AgilePredictClient(),
        meters,
        REGION,
    )


@responses.activate
def test_fixed_tariff_actual_cost_and_projection(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-08-06")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
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
        # One elapsed day (2026-07-06), 2.0 kWh consumed.
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )
    retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 1
    row = stored[0]
    assert row.billing_period_start == date(2026, 7, 6)
    assert row.billing_period_end == date(2026, 8, 6)
    # (2.0 kWh @ 20.00p) + 48.00p standing charge = 88.00p -> £0.88
    assert row.actual_cost_to_date == Decimal("0.88")
    # total_period_days = Jul6..Aug6 inclusive = 32; remaining_days = 32 - 1
    # elapsed day (Jul6) = 31, at 2.0 kWh/day average, same 20.00p rate +
    # 48.00p standing charge/day.
    remaining_days = 31
    expected_remaining = (
        remaining_days * (Decimal("2.0") * Decimal("20.00") + Decimal("48.00")) / 100
    )
    assert row.projected_total_cost == row.actual_cost_to_date + expected_remaining
    agile_calls = [c for c in responses.calls if c.request.url == AGILE_ENDPOINT]
    assert not agile_calls


@responses.activate
def test_standing_charge_is_charged_exactly_once_per_day_with_a_non_midnight_as_of(
    mariadb_client: MariaDBClient,
) -> None:
    # Regression test: the daily job always runs at a non-midnight time
    # (DAILY_JOB_TIME = "04:00"). Billing period end (Jul 10) is the last
    # inclusive billable day, so the full period is Jul6..Jul10 = 5 days.
    # With as_of = Jul8 04:00: elapsed = {Jul6, Jul7, Jul8} (3 days, each
    # already charged a full standing fee via the elapsed query/gap-fill);
    # remaining_days (whole future days, for standing charge only) =
    # 5 total - 3 elapsed = 2, representing {Jul9, Jul10} -- not {Jul8,
    # Jul9}, since remaining_days always excludes as_of.date() ("today").
    # 3 + 2 = 5 standing-charge-days total, matching the period length
    # exactly, with today's standing fee counted once, not twice.
    _mock_billing_period("2026-07-06", "2026-07-10")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
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
        # Elapsed days Jul6, Jul7, Jul8 (as_of = Jul8 04:00) each get 6.0 kWh
        # -- chosen (rather than a rounder-looking value) so the partial-
        # today variable-cost fraction below divides out to a clean number.
        for day in (6, 7, 8):
            s.add(
                model.consumption(
                    id=f"E202607{day:02d}000000",
                    energy="E",
                    period_from=datetime(2026, 7, day, 0, 0, tzinfo=timezone.utc),
                    period_to=datetime(2026, 7, day, 0, 30, tzinfo=timezone.utc),
                    raw_value=Decimal("6.0"),
                    unit="kWh",
                    est_kwh=Decimal("6.0"),
                )
            )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )
    retriever.refresh(as_of=datetime(2026, 7, 8, 4, 0, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    day_charge = Decimal("6.0") * Decimal("20.00") + Decimal("48.00")  # 168.00p
    # actual_cost_to_date: 3 elapsed days (Jul6, Jul7, Jul8), each already
    # fully charged its own standing fee -- 3 * 168.00p = 504.00p -> £5.04.
    assert row.actual_cost_to_date == 3 * day_charge / 100
    # remaining_days = 2 (Jul9, Jul10) -> standing_cost = 2*48.00 = 96.00p.
    # remaining_hours spans from Jul8 04:00 through the end of Jul10
    # (period_end_boundary = Jul11 00:00) = 68 hours -- covering the rest
    # of Jul8 (already elapsed for standing-charge purposes, but NOT yet
    # priced for its remaining consumption) plus Jul9 and Jul10 in full.
    # variable_cost = (68/24) * 6.0 kWh/day * 20.00p = 340.00p.
    # remaining total = (340.00 + 96.00)/100 = £4.36.
    assert row.projected_total_cost == 3 * day_charge / 100 + Decimal("4.36")


def _seed_agile_agreement_and_rate(
    s: Session, standing_charge: str = "50.00", unit_rate: str = "25.00"
) -> None:
    s.add(
        model.agreement(
            id="E20220101000000",
            energy="E",
            product_code=AGILE_PRODUCT_CODE,
            tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}",
            valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
            valid_to=None,
        )
    )
    s.add(
        model.product_rate(
            id=f"{AGILE_PRODUCT_CODE}_{REGION}_202607010000",
            product_code=AGILE_PRODUCT_CODE,
            region=REGION,
            valid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            valid_to=None,
            unit_rate=Decimal(unit_rate),
            standing_charge=Decimal(standing_charge),
        )
    )


@responses.activate
def test_agile_tariff_costs_each_remaining_slot_at_its_own_rate_not_a_flat_average(
    mariadb_client: MariaDBClient,
) -> None:
    # A flat per-slot rate can't distinguish true per-slot costing from a
    # flat-average shortcut -- this fixture uses two different rates across
    # the only two remaining slots so an incorrect averaged implementation
    # would produce a visibly different total.
    _mock_billing_period("2026-07-06", "2026-07-07")
    _mock_agile_forecast(
        [
            {
                "date_time": "2026-07-06T23:00:00+00:00",
                "agile_pred": "10.00",
                "agile_low": "10.00",
                "agile_high": "10.00",
            },
            {
                "date_time": "2026-07-06T23:30:00+00:00",
                "agile_pred": "30.00",
                "agile_low": "30.00",
                "agile_high": "30.00",
            },
        ]
    )

    with mariadb_client.session_write_scope() as s:
        _seed_agile_agreement_and_rate(s, standing_charge="50.00", unit_rate="25.00")
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("24.0"),
                unit="kWh",
                est_kwh=Decimal("24.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}"
                )
            ],
        )
    )
    retriever.refresh(as_of=datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    # actual: (24.0 kWh @ 25.00p) + 50.00p standing = 650.00p -> £6.50
    assert row.actual_cost_to_date == Decimal("6.50")
    # future_daily_kwh = 24.0 (one elapsed day); per_slot_kwh = 24.0/48 = 0.5.
    # The remaining window spans the rest of Jul6 (23:00, 23:30 -- the only
    # two real forecast entries) *and* all of Jul7 (the inclusive billing
    # period end), which tiling fills by repeating those same two entries
    # (only one real source day exists to tile from) -- 4 slots total:
    # 2 * (0.5*10.00 + 0.5*30.00) = 40.00p variable; standing = 1 remaining
    # day * 50.00p = 50.00p -> (40.00+50.00)/100 = £0.90
    assert row.projected_total_cost == Decimal("6.50") + Decimal("0.90")


@responses.activate
def test_agile_tariff_prices_the_inclusive_final_billable_day_not_just_up_to_it(
    mariadb_client: MariaDBClient,
) -> None:
    # Regression test: the remaining-days slot window must extend through
    # billing_period_end's own half-hourly slots, not stop at its midnight
    # boundary. Uses two different flat rates on two different real
    # (non-tiled) remaining days so a window that silently excluded the
    # final day would produce a visibly smaller, wrong total.
    _mock_billing_period("2026-07-06", "2026-07-08")
    _mock_agile_forecast(
        _flat_agile_prices(date(2026, 7, 7), 1, "10.00")
        + _flat_agile_prices(date(2026, 7, 8), 1, "50.00")
    )

    with mariadb_client.session_write_scope() as s:
        _seed_agile_agreement_and_rate(s, standing_charge="0.00")
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}"
                )
            ],
        )
    )
    retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    # future_daily_kwh = 2.0 (one elapsed day); 0.00p standing charge
    # isolates the variable-cost total. Correct: both remaining days priced
    # -- 2.0*10.00 (Jul7) + 2.0*50.00 (Jul8, the inclusive end date) =
    # 120.00p -> £1.20. A window that excluded Jul8 would give only
    # 2.0*10.00 = 20.00p -> £0.20.
    remaining = row.projected_total_cost - row.actual_cost_to_date
    assert remaining == Decimal("1.20")


@responses.activate
def test_agile_tariff_remaining_days_within_the_real_forecast_horizon(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-07-10")
    _mock_agile_forecast(_flat_agile_prices(date(2026, 7, 6), 7, "15.00"))

    with mariadb_client.session_write_scope() as s:
        _seed_agile_agreement_and_rate(s)
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}"
                )
            ],
        )
    )
    retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    # 1 elapsed day: (2.0 kWh @ 25.00p) + 50.00p standing = 100.00p -> £1.00
    assert row.actual_cost_to_date == Decimal("1.00")
    # total_period_days = Jul6..Jul10 inclusive = 5; remaining_days = 5 - 1
    # elapsed day = 4 (Jul7-Jul10, the inclusive end date), flat 15.00p/kWh
    # throughout (all within the real forecast, no tiling):
    # 4 * (2.0*15.00 + 50.00) = 320.00p
    assert row.projected_total_cost == Decimal("1.00") + Decimal("3.20")

    # The fetched forecast must be persisted for the pre-existing "Price
    # Curve" Grafana panel (reads agile_forecast) to have data to plot --
    # fetching it for the in-memory projection isn't enough on its own.
    with mariadb_client.session_read_scope() as session:
        forecast_rows = session.query(model.agile_forecast).all()
    assert len(forecast_rows) == 48 * 7
    assert all(r.region == REGION for r in forecast_rows)
    assert all(r.forecast_unit_rate == Decimal("15.00") for r in forecast_rows)


@responses.activate
def test_agile_tariff_remaining_days_beyond_the_forecast_horizon_uses_tiling(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-07-25")
    # Only 7 real days of forecast (Jul6-Jul12) -- the remaining window
    # (Jul7-Jul25, 19 days) needs Jul13-Jul25 (13 days) from tiling.
    _mock_agile_forecast(_flat_agile_prices(date(2026, 7, 6), 7, "15.00"))

    with mariadb_client.session_write_scope() as s:
        _seed_agile_agreement_and_rate(s)
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}"
                )
            ],
        )
    )
    # Should not raise despite the forecast running out before the billing
    # period ends -- tiling fills the remainder.
    retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    # Flat 15.00p rate throughout (both real and tiled days repeat the same
    # flat price), so the flat-rate formula still applies exactly:
    # total_period_days = Jul6..Jul25 inclusive = 20; remaining_days =
    # 20 - 1 elapsed day = 19 (Jul7-Jul25, the inclusive end date);
    # 19 * (2.0*15.00 + 50.00) = 1520.00p
    assert row.projected_total_cost == Decimal("1.00") + Decimal("15.20")


@responses.activate
def test_a_zero_consumption_elapsed_day_still_contributes_its_standing_charge(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-08-06")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
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
        # Jul 6 has consumption; Jul 7 (also elapsed, as_of = Jul 8) has
        # none at all -- no consumption row to join a standing charge
        # through, so it must be filled in independently.
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )
    retriever.refresh(as_of=datetime(2026, 7, 8, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        row = session.query(model.cost_forecast).one()

    # Jul6: (2.0*20.00 + 48.00)/100 = 0.88; Jul7 (zero kWh): 48.00/100 = 0.48
    assert row.actual_cost_to_date == Decimal("1.36")
    # future_daily_kwh = avg([2.0, 0.0]) = 1.0; total_period_days =
    # Jul6..Aug6 inclusive = 32; remaining_days = 32 - 2 elapsed days = 30
    remaining_days = 30
    expected_remaining = (
        remaining_days * (Decimal("1.0") * Decimal("20.00") + Decimal("48.00")) / 100
    )
    assert row.projected_total_cost == Decimal("1.36") + expected_remaining


@responses.activate
def test_no_electricity_meter_raises_a_clear_error(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-08-06")
    retriever = CostForecastRetriever(_source(mariadb_client, []))

    with pytest.raises(RuntimeError, match="[Nn]o electricity meter"):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))


@responses.activate
def test_no_current_agreement_raises_a_clear_error(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-08-06")
    lapsed_meter = Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2021, 1, 1, tzinfo=timezone.utc),
            )
        ],
    )
    retriever = CostForecastRetriever(_source(mariadb_client, [lapsed_meter]))

    with pytest.raises(RuntimeError, match="[Nn]o current .*agreement"):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))


@responses.activate
def test_current_agreement_with_a_bounded_valid_to_still_matches(
    mariadb_client: MariaDBClient,
) -> None:
    # Regression test: real Agile contracts renew as fixed one-year terms --
    # Octopus's API never returns valid_to=None for them, not even for the
    # currently-active agreement (confirmed live against a real account's
    # agreement table). "Current" must mean "as_of falls within this
    # agreement's range", not "this agreement has no end date".
    _mock_billing_period("2026-07-06", "2026-08-06")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
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
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    valid_to=datetime(2027, 5, 24, tzinfo=timezone.utc)
                )
            ],
        )
    )
    retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.cost_forecast).all()

    assert len(stored) == 1
    assert stored[0].actual_cost_to_date == Decimal("0.88")


@responses.activate
def test_no_current_product_rate_raises_a_clear_error(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-07-10")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
        # Covers Jul6's consumption (so the elapsed query succeeds) but
        # expires before as_of (Jul7 00:00), so the remaining-cost lookup
        # for "the current rate" finds nothing.
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202601010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )

    with pytest.raises(RuntimeError, match="[Nn]o product_rate found"):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))


@responses.activate
def test_no_product_rate_for_a_zero_consumption_elapsed_day_raises_and_writes_no_row(
    mariadb_client: MariaDBClient,
) -> None:
    # A missing rate for a gap-filled (zero-consumption) elapsed day must
    # fail the whole refresh, not silently omit that day's standing charge
    # from actual_cost_to_date -- money calculations shouldn't quietly
    # produce a plausible-but-wrong number, matching this file's established
    # "raise rather than guess" philosophy elsewhere (e.g. the current-rate
    # lookup in _project_remaining_cost).
    _mock_billing_period("2026-07-06", "2026-07-10")

    with mariadb_client.session_write_scope() as s:
        s.add(
            model.agreement(
                id="E20220101000000",
                energy="E",
                product_code=PRODUCT_CODE,
                tariff_code=f"E-1R-{PRODUCT_CODE}-{REGION}",
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        )
        # Rate A covers Jul6's real consumption; rate B covers as_of (Jul8
        # 00:00) so the *remaining-cost* lookup succeeds -- but neither
        # covers Jul7 12:00 (the gap-fill's midday lookup for Jul7, which
        # has zero consumption rows), isolating the gap-fill path's own
        # rate lookup from the already-tested remaining-cost lookup.
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202601010000",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
                unit_rate=Decimal("20.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.product_rate(
                id=f"{PRODUCT_CODE}_{REGION}_202607071300",
                product_code=PRODUCT_CODE,
                region=REGION,
                valid_from=datetime(2026, 7, 7, 13, 0, tzinfo=timezone.utc),
                valid_to=None,
                unit_rate=Decimal("22.00"),
                standing_charge=Decimal("48.00"),
            )
        )
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )

    with pytest.raises(RuntimeError, match="[Nn]o product_rate found"):
        retriever.refresh(as_of=datetime(2026, 7, 8, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        assert session.query(model.cost_forecast).count() == 0


@responses.activate
def test_kraken_unreachable_raises_and_writes_no_row(
    mariadb_client: MariaDBClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"errors": [{"message": "Invalid API key"}]},
        status=200,
    )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )

    with pytest.raises(APIError):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        assert session.query(model.cost_forecast).count() == 0


@responses.activate
def test_kraken_unreachable_leaves_a_previous_row_unchanged(
    mariadb_client: MariaDBClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    previous = CostForecast(
        billing_period_start=date(2026, 6, 6),
        billing_period_end=date(2026, 7, 6),
        actual_cost_to_date=Decimal("10.00"),
        projected_total_cost=Decimal("20.00"),
        computed_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )
    mariadb_client.write_cost_forecast(previous)
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"errors": [{"message": "Invalid API key"}]},
        status=200,
    )

    retriever = CostForecastRetriever(
        _source(mariadb_client, [_make_electricity_meter()])
    )
    with pytest.raises(APIError):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        rows = session.query(model.cost_forecast).all()
    assert len(rows) == 1
    assert rows[0].projected_total_cost == Decimal("20.00")


@responses.activate
def test_agile_predict_unreachable_raises_and_writes_no_row(
    mariadb_client: MariaDBClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    _mock_billing_period("2026-07-06", "2026-07-10")
    responses.add(
        responses.GET,
        AGILE_ENDPOINT,
        json={"detail": "service unavailable"},
        status=503,
    )

    with mariadb_client.session_write_scope() as s:
        _seed_agile_agreement_and_rate(s)
        s.add(
            model.consumption(
                id="E20260706000000",
                energy="E",
                period_from=datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc),
                period_to=datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc),
                raw_value=Decimal("2.0"),
                unit="kWh",
                est_kwh=Decimal("2.0"),
            )
        )

    retriever = CostForecastRetriever(
        _source(
            mariadb_client,
            [
                _make_electricity_meter(
                    tariff_code=f"E-1R-{AGILE_PRODUCT_CODE}-{REGION}"
                )
            ],
        )
    )
    with pytest.raises(APIError):
        retriever.refresh(as_of=datetime(2026, 7, 7, tzinfo=timezone.utc))

    with mariadb_client.session_read_scope() as session:
        assert session.query(model.cost_forecast).count() == 0

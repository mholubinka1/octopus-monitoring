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

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime
    ) -> List[DailyCostSummary]:
        return self._mariadb.read_elapsed_billing_period_costs(period_from, period_to)

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Optional[Rate]:
        return self._mariadb.read_current_product_rate(product_code, region, as_of)

    def persist_cost_forecast(self, forecast: CostForecast) -> None:
        self._mariadb.write_cost_forecast(forecast)


def _make_electricity_meter(
    tariff_code: str = f"E-1R-{PRODUCT_CODE}-{REGION}",
) -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code=tariff_code,
                valid_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
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
        BillingPeriodClient(settings, KrakenTransport(settings)),
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
    # remaining_days = billing_period_end (Aug 6) - as_of.date() (Jul 7) = 30,
    # at 2.0 kWh/day average, same 20.00p rate + 48.00p standing charge/day.
    remaining_days = 30
    expected_remaining = (
        remaining_days * (Decimal("2.0") * Decimal("20.00") + Decimal("48.00")) / 100
    )
    assert row.projected_total_cost == row.actual_cost_to_date + expected_remaining
    agile_calls = [c for c in responses.calls if c.request.url == AGILE_ENDPOINT]
    assert not agile_calls


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
    # remaining_days = Jul10 - Jul7 = 3, flat 15.00p/kWh throughout (all
    # within the real forecast, no tiling): 3 * (2.0*15.00 + 50.00) = 240.00p
    assert row.projected_total_cost == Decimal("1.00") + Decimal("2.40")


@responses.activate
def test_agile_tariff_remaining_days_beyond_the_forecast_horizon_uses_tiling(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_billing_period("2026-07-06", "2026-07-25")
    # Only 7 real days of forecast -- billing period end is 19 days out,
    # so days 8-18 (11 days) must come from tiling.
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
    # remaining_days = Jul25 - Jul7 = 18; 18 * (2.0*15.00 + 50.00) = 1440.00p
    assert row.projected_total_cost == Decimal("1.00") + Decimal("14.40")


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
    # future_daily_kwh = avg([2.0, 0.0]) = 1.0; remaining_days = Aug6-Jul8 = 29
    remaining_days = 29
    expected_remaining = (
        remaining_days * (Decimal("1.0") * Decimal("20.00") + Decimal("48.00")) / 100
    )
    assert row.projected_total_cost == Decimal("1.36") + expected_remaining


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

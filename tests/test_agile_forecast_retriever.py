from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import responses
from common.exceptions import APIError
from data.agile_forecast import AgileForecastRetriever
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.octopus.agile_predict import AgilePredictClient
from data.octopus.model import AgileForecastReading
from data.octopus.x2r import X2rClient

AGILE_ENDPOINT = "https://agilepredict.com/api/H/"
X2R_ENDPOINT = "https://api.x2r.uk/agile/H"
REGION = "H"


class _RealAgileForecastSource:
    """Real MariaDBClient/AgilePredictClient/X2rClient underneath -- HTTP
    calls mocked via `responses`, DB is the real SQLite fixture -- mirroring
    _RealCostForecastSource's pattern in test_cost_forecast_retriever.py."""

    def __init__(
        self,
        mariadb: MariaDBClient,
        agile_predict_client: AgilePredictClient,
        x2r_client: X2rClient,
        region_code: str,
    ) -> None:
        self._mariadb = mariadb
        self._agile_predict_client = agile_predict_client
        self._x2r_client = x2r_client
        self.region_code = region_code

    def fetch_agile_forecast(self, region: str) -> list[AgileForecastReading]:
        return self._agile_predict_client.get_forecast(region)

    def fetch_agile_forecast_fallback(self, region: str) -> list[AgileForecastReading]:
        return self._x2r_client.get_forecast(region)

    def persist_agile_forecast(
        self,
        region: str,
        readings: list[AgileForecastReading],
        fetched_at: datetime,
    ) -> None:
        self._mariadb.write_agile_forecast(region, readings, fetched_at)


def _source(mariadb: MariaDBClient) -> _RealAgileForecastSource:
    return _RealAgileForecastSource(mariadb, AgilePredictClient(), X2rClient(), REGION)


def _agile_predict_price_entry(offset_minutes: int, pred: str) -> dict:
    date_time = datetime(2026, 7, 22, 0, 0, tzinfo=UTC) + timedelta(
        minutes=offset_minutes
    )
    return {"date_time": date_time.isoformat(), "agile_pred": pred}


def _mock_agile_predict(prices: list[dict]) -> None:
    responses.add(
        responses.GET,
        AGILE_ENDPOINT,
        json=[{"name": f"Region | {REGION}", "prices": prices}],
        status=200,
    )


def _x2r_price_entry(offset_minutes: int, price: str) -> dict:
    date = datetime(2026, 7, 22, 0, 0, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    return {"date": date.isoformat(), "price": price}


def _mock_x2r(forecast: list[dict]) -> None:
    responses.add(
        responses.GET,
        X2R_ENDPOINT,
        json={
            "forecast_at": "2026-07-22T04:15:00+01:00",
            "region": REGION,
            "region_name": f"Region {REGION}",
            "prices": {"forecast": forecast, "day_ahead": [], "actual": []},
        },
        status=200,
    )


@responses.activate
def test_primary_source_succeeding_persists_its_readings_and_never_calls_the_fallback(
    mariadb_client: MariaDBClient,
) -> None:
    _mock_agile_predict([_agile_predict_price_entry(0, "21.19")])

    AgileForecastRetriever(_source(mariadb_client)).refresh(
        as_of=datetime(2026, 7, 22, tzinfo=UTC)
    )

    with mariadb_client.session_read_scope() as session:
        rows = session.query(model.agile_forecast).all()

    assert len(rows) == 1
    assert rows[0].forecast_unit_rate == Decimal("21.19")
    x2r_calls = [c for c in responses.calls if c.request.url == X2R_ENDPOINT]
    assert not x2r_calls


@responses.activate
def test_primary_source_failing_falls_back_to_x2r_and_persists_its_readings(
    mariadb_client: MariaDBClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        AGILE_ENDPOINT,
        json={"detail": "service unavailable"},
        status=503,
    )
    _mock_x2r([_x2r_price_entry(0, "18.50")])

    AgileForecastRetriever(_source(mariadb_client)).refresh(
        as_of=datetime(2026, 7, 22, tzinfo=UTC)
    )

    with mariadb_client.session_read_scope() as session:
        rows = session.query(model.agile_forecast).all()

    assert len(rows) == 1
    assert rows[0].forecast_unit_rate == Decimal("18.50")


@responses.activate
def test_both_sources_failing_raises_and_persists_nothing(
    mariadb_client: MariaDBClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        AGILE_ENDPOINT,
        json={"detail": "service unavailable"},
        status=503,
    )
    responses.add(
        responses.GET,
        X2R_ENDPOINT,
        json={"detail": "service unavailable"},
        status=503,
    )

    with pytest.raises(APIError):
        AgileForecastRetriever(_source(mariadb_client)).refresh(
            as_of=datetime(2026, 7, 22, tzinfo=UTC)
        )

    with mariadb_client.session_read_scope() as session:
        assert session.query(model.agile_forecast).count() == 0

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests
import responses
from common.exceptions import APIError
from data.octopus.agile_predict import AgilePredictClient

REGION = "H"
ENDPOINT = f"https://agilepredict.com/api/{REGION}/"


def _price_entry(offset_minutes: int, pred: str) -> dict:
    date_time = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc) + timedelta(
        minutes=offset_minutes
    )
    return {
        "date_time": date_time.isoformat(),
        "agile_pred": pred,
        "agile_low": pred,
        "agile_high": pred,
    }


def _mock_forecast(prices: list) -> None:
    responses.add(
        responses.GET,
        ENDPOINT,
        json=[
            {
                "name": f"Region | {REGION} 2026-07-22 04:15",
                "created_at": "2026-07-22T04:15:42.793238+01:00",
                "prices": prices,
            }
        ],
        status=200,
    )


@responses.activate
def test_get_forecast_maps_agile_pred_to_unit_rate_with_thirty_minute_periods() -> None:
    _mock_forecast([_price_entry(0, "21.19"), _price_entry(30, "20.98")])

    readings = AgilePredictClient().get_forecast(REGION)

    assert len(readings) == 2
    assert readings[0].period_from == datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
    assert readings[0].period_to == datetime(2026, 7, 22, 0, 30, tzinfo=timezone.utc)
    assert readings[0].unit_rate == Decimal("21.19")
    assert readings[1].period_from == datetime(2026, 7, 22, 0, 30, tzinfo=timezone.utc)


@responses.activate
def test_empty_prices_array_raises_a_clear_error() -> None:
    _mock_forecast([])

    with pytest.raises(APIError, match=REGION):
        AgilePredictClient().get_forecast(REGION)


@responses.activate
def test_non_200_response_raises_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ENDPOINT,
        json={"detail": "not found"},
        status=404,
    )

    with pytest.raises(APIError, match="not found"):
        AgilePredictClient().get_forecast(REGION)


@responses.activate
def test_connection_failure_raises_a_descriptive_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ENDPOINT,
        body=requests.exceptions.ConnectTimeout("connection timed out"),
    )

    with pytest.raises(
        RuntimeError, match="fetch Agile forecast.*connection timed out"
    ):
        AgilePredictClient().get_forecast(REGION)

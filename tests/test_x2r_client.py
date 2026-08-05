from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import requests
import responses
from common.exceptions import APIError
from data.octopus.x2r import X2rClient

REGION = "H"
ENDPOINT = f"https://api.x2r.uk/agile/{REGION}"


def _price_entry(offset_minutes: int, price: str) -> dict:
    date = datetime(2026, 7, 22, 0, 0, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    return {"date": date.isoformat(), "price": price}


def _mock_forecast(
    forecast: list[dict],
    day_ahead: list[dict] | None = None,
    actual: list[dict] | None = None,
) -> None:
    responses.add(
        responses.GET,
        ENDPOINT,
        json={
            "forecast_at": "2026-07-22T04:15:00+01:00",
            "region": REGION,
            "region_name": f"Region {REGION}",
            "prices": {
                "forecast": forecast,
                "day_ahead": day_ahead or [],
                "actual": actual or [],
            },
        },
        status=200,
    )


@responses.activate
def test_get_forecast_maps_forecast_prices_to_unit_rate_with_thirty_minute_periods() -> (
    None
):
    _mock_forecast([_price_entry(0, "21.19"), _price_entry(30, "20.98")])

    readings = X2rClient().get_forecast(REGION)

    assert len(readings) == 2
    assert readings[0].period_from == datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    assert readings[0].period_to == datetime(2026, 7, 22, 0, 30, tzinfo=UTC)
    assert readings[0].unit_rate == Decimal("21.19")
    assert readings[1].period_from == datetime(2026, 7, 22, 0, 30, tzinfo=UTC)


@responses.activate
def test_day_ahead_and_actual_prices_are_not_included_in_the_forecast() -> None:
    _mock_forecast(
        forecast=[_price_entry(0, "21.19")],
        day_ahead=[_price_entry(0, "19.00")],
        actual=[_price_entry(0, "18.50")],
    )

    readings = X2rClient().get_forecast(REGION)

    assert len(readings) == 1
    assert readings[0].unit_rate == Decimal("21.19")


@responses.activate
def test_empty_forecast_array_raises_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    _mock_forecast([])

    with pytest.raises(APIError, match=REGION):
        X2rClient().get_forecast(REGION)


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
        X2rClient().get_forecast(REGION)


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
        X2rClient().get_forecast(REGION)

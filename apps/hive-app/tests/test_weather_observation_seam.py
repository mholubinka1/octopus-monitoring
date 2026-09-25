import pytest
import requests
import responses
from pydantic import ValidationError

from hive_app.common.config import LocationSettings, WeatherUndergroundSettings
from hive_app.data.mysql import model
from hive_app.data.mysql.client import MariaDBClient
from hive_app.data.open_meteo_client import OpenMeteoClient
from hive_app.data.weather_underground_client import WeatherUndergroundClient

WU_ENDPOINT = "https://api.weather.com/v2/pws/observations/current"
OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


@responses.activate
def test_a_wunderground_observation_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        WU_ENDPOINT,
        json={
            "observations": [
                {
                    "obsTimeUtc": "2026-09-25T12:00:00Z",
                    "humidity": 72,
                    "metric": {
                        "temp": 14.5,
                        "pressure": 1012.3,
                        "windSpeed": 8.1,
                        "precipTotal": 0.0,
                    },
                }
            ]
        },
        status=200,
    )

    client = WeatherUndergroundClient(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4")
    )

    observation = client.get_current_observation()
    mariadb_client.write_weather_observation(observation)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.weather_observation).all()

    assert len(stored) == 1
    assert stored[0].source == "wunderground"
    assert stored[0].temp == 14.5
    assert stored[0].humidity == 72
    assert stored[0].pressure == 1012.3
    assert stored[0].wind_speed == 8.1
    assert stored[0].precipitation == 0.0


@responses.activate
def test_an_open_meteo_observation_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        OPEN_METEO_ENDPOINT,
        json={
            "current": {
                "time": "2026-09-25T12:00",
                "temperature_2m": 14.5,
                "relative_humidity_2m": 72,
                "surface_pressure": 1012.3,
                "wind_speed_10m": 8.1,
                "precipitation": 0.0,
            }
        },
        status=200,
    )

    client = OpenMeteoClient(LocationSettings(latitude=51.5, longitude=-0.1))

    observation = client.get_current_observation()

    # Unlike get_forecast() (which requests Europe/London for ADR-0010 day
    # bucketing), this request must stay UTC -- observed_at is a point-in-
    # time instant, not a calendar day, so forcing UTC just avoids guessing
    # an offset on the naive timestamp Open-Meteo returns.
    assert len(responses.calls) == 1
    assert "timezone=UTC" in responses.calls[0].request.url

    mariadb_client.write_weather_observation(observation)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.weather_observation).all()

    assert len(stored) == 1
    assert stored[0].source == "open-meteo"
    assert stored[0].temp == 14.5
    assert stored[0].humidity == 72
    assert stored[0].pressure == 1012.3
    assert stored[0].wind_speed == 8.1
    assert stored[0].precipitation == 0.0


@responses.activate
def test_a_wunderground_http_failure_does_not_leak_the_api_key() -> None:
    secret_api_key = "do-not-log-this-fake-key"
    responses.add(responses.GET, WU_ENDPOINT, status=500)

    client = WeatherUndergroundClient(
        WeatherUndergroundSettings(api_key=secret_api_key, station_id="IBECKE4")
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_current_observation()

    assert secret_api_key not in str(exc_info.value)
    # `raise ... from None` -- proves the original HTTPError (whose message
    # embeds the request URL, including the apiKey query param) is fully
    # replaced rather than chained, so it can't surface via a traceback or
    # exc_info=True logging even though this test only inspects the message.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


@responses.activate
def test_a_wunderground_connection_failure_does_not_leak_the_api_key() -> None:
    # A connection-level failure (raised by requests.get() itself, before
    # raise_for_status() is ever reached) also embeds the prepared request
    # URL -- including the apiKey query param -- in its message. This must
    # be redacted the same way an HTTP error status is.
    secret_api_key = "do-not-log-this-fake-key"
    responses.add(
        responses.GET,
        WU_ENDPOINT,
        body=requests.exceptions.ConnectionError(
            f"Failed to establish a new connection: {WU_ENDPOINT}?apiKey={secret_api_key}"
        ),
    )

    client = WeatherUndergroundClient(
        WeatherUndergroundSettings(api_key=secret_api_key, station_id="IBECKE4")
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_current_observation()

    assert secret_api_key not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


@responses.activate
def test_a_wunderground_response_with_an_empty_observations_array_is_rejected() -> None:
    responses.add(
        responses.GET,
        WU_ENDPOINT,
        json={"observations": []},
        status=200,
    )

    client = WeatherUndergroundClient(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4")
    )

    with pytest.raises(RuntimeError, match="no observations"):
        client.get_current_observation()


@responses.activate
def test_a_wunderground_response_with_a_non_finite_field_is_rejected() -> None:
    # Python's json module accepts NaN/Infinity as non-standard JSON
    # literals -- FiniteFloat must reject them rather than silently
    # persisting a NaN/Infinity value to the weather_observation table.
    responses.add(
        responses.GET,
        WU_ENDPOINT,
        json={
            "observations": [
                {
                    "obsTimeUtc": "2026-09-25T12:00:00Z",
                    "humidity": 72,
                    "metric": {
                        "temp": float("nan"),
                        "pressure": 1012.3,
                        "windSpeed": 8.1,
                        "precipTotal": 0.0,
                    },
                }
            ]
        },
        status=200,
    )

    client = WeatherUndergroundClient(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4")
    )

    with pytest.raises(ValidationError, match="finite"):
        client.get_current_observation()


@responses.activate
def test_an_open_meteo_response_with_a_non_finite_field_is_rejected() -> None:
    responses.add(
        responses.GET,
        OPEN_METEO_ENDPOINT,
        json={
            "current": {
                "time": "2026-09-25T12:00",
                "temperature_2m": float("inf"),
                "relative_humidity_2m": 72,
                "surface_pressure": 1012.3,
                "wind_speed_10m": 8.1,
                "precipitation": 0.0,
            }
        },
        status=200,
    )

    client = OpenMeteoClient(LocationSettings(latitude=51.5, longitude=-0.1))

    with pytest.raises(ValidationError, match="finite"):
        client.get_current_observation()

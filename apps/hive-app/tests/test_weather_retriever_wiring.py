import pytest
import requests
import responses

from hive_app.common.config import LocationSettings, WeatherUndergroundSettings
from hive_app.data.mysql import model
from hive_app.data.mysql.client import MariaDBClient
from hive_app.main import _build_weather_retriever

WU_ENDPOINT = "https://api.weather.com/v2/pws/observations/current"
OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


def test_build_weather_retriever_returns_none_when_wunderground_is_missing(
    mariadb_client: MariaDBClient,
) -> None:
    retriever = _build_weather_retriever(
        None, LocationSettings(latitude=51.5, longitude=-0.1), mariadb_client
    )

    assert retriever is None


def test_build_weather_retriever_returns_none_when_location_is_missing(
    mariadb_client: MariaDBClient,
) -> None:
    retriever = _build_weather_retriever(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4"),
        None,
        mariadb_client,
    )

    assert retriever is None


@responses.activate
def test_build_weather_retriever_wires_a_real_source_when_both_settings_are_present(
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

    retriever = _build_weather_retriever(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4"),
        LocationSettings(latitude=51.5, longitude=-0.1),
        mariadb_client,
    )
    assert retriever is not None

    retriever.refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.weather_observation).all()

    assert len(stored) == 1
    assert stored[0].source == "wunderground"


@responses.activate
def test_a_both_sources_failing_makes_no_call_beyond_wunderground_and_open_meteo(
    mariadb_client: MariaDBClient,
) -> None:
    # No ntfy (or any other) endpoint is registered here -- an unexpected
    # HTTP call from a regressed wiring (e.g. weather failures somehow
    # notifying, which AC3 explicitly rules out -- that's #509's job, not
    # this one) would raise ConnectionError instead of surfacing as the
    # plain propagated ConnectionError this test expects from Open-Meteo.
    responses.add(responses.GET, WU_ENDPOINT, status=500)
    responses.add(responses.GET, OPEN_METEO_ENDPOINT, status=500)

    retriever = _build_weather_retriever(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4"),
        LocationSettings(latitude=51.5, longitude=-0.1),
        mariadb_client,
    )
    assert retriever is not None

    with pytest.raises(requests.HTTPError):
        retriever.refresh()

    assert len(responses.calls) == 2
    assert responses.calls[0].request.url.startswith(WU_ENDPOINT)
    assert responses.calls[1].request.url.startswith(OPEN_METEO_ENDPOINT)


@responses.activate
def test_wunderground_returning_no_observations_falls_back_to_open_meteo(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        WU_ENDPOINT,
        json={"observations": []},
        status=200,
    )
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

    retriever = _build_weather_retriever(
        WeatherUndergroundSettings(api_key="test-key", station_id="IBECKE4"),
        LocationSettings(latitude=51.5, longitude=-0.1),
        mariadb_client,
    )
    assert retriever is not None

    retriever.refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.weather_observation).all()

    assert len(stored) == 1
    assert stored[0].source == "open-meteo"

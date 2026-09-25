from unittest.mock import Mock

import pytest
from schedule import Scheduler

from hive_app.data.mysql import model
from hive_app.data.mysql.client import MariaDBClient
from hive_app.data.weather import WeatherRetriever
from hive_app.main import register_weather_forecast_refresh_job


def test_weather_forecast_refresh_job_runs_on_a_60_minute_interval(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()

    job = register_weather_forecast_refresh_job(
        scheduler, Mock(spec=WeatherRetriever), mariadb_client
    )

    assert job.interval == 60
    assert job.unit == "minutes"


def test_a_successful_weather_forecast_refresh_is_recorded_as_a_successful_job_run(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    weather = Mock(spec=WeatherRetriever)

    job = register_weather_forecast_refresh_job(scheduler, weather, mariadb_client)
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "weather_forecast_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_a_persistently_failing_weather_forecast_refresh_retries_with_backoff(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_delays: list[int] = []
    monkeypatch.setattr("hive_app.common.decorator.time.sleep", sleep_delays.append)
    scheduler = Scheduler()
    weather = Mock(spec=WeatherRetriever)
    weather.refresh_forecast.side_effect = RuntimeError(
        "api.open-meteo.com unreachable"
    )

    job = register_weather_forecast_refresh_job(scheduler, weather, mariadb_client)
    job.run().join()

    assert sleep_delays == [60, 120, 240, 480]
    assert weather.refresh_forecast.call_count == 5

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 5
    assert all(run.status == "failure" for run in runs)
    assert all(run.error_message == "api.open-meteo.com unreachable" for run in runs)

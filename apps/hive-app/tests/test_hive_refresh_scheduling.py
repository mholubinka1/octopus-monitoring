from unittest.mock import Mock

import pytest
from hive_app.data.heating import HeatingRetriever
from hive_app.data.mysql import model
from hive_app.data.mysql.client import MariaDBClient
from hive_app.main import register_heating_refresh_job, run_pending_safely
from schedule import Scheduler


def test_heating_refresh_job_runs_on_a_120_second_interval(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()

    job = register_heating_refresh_job(
        scheduler, Mock(spec=HeatingRetriever), mariadb_client
    )

    assert job.interval == 120
    assert job.unit == "seconds"


def test_a_successful_heating_refresh_is_recorded_as_a_successful_job_run(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    heating = Mock(spec=HeatingRetriever)

    job = register_heating_refresh_job(scheduler, heating, mariadb_client)
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "heating_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_a_persistently_failing_heating_refresh_retries_with_exponential_backoff(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_delays: list[int] = []
    monkeypatch.setattr("hive_app.common.decorator.time.sleep", sleep_delays.append)
    scheduler = Scheduler()
    heating = Mock(spec=HeatingRetriever)
    heating.refresh.side_effect = RuntimeError("Hive backend unreachable")

    job = register_heating_refresh_job(scheduler, heating, mariadb_client)
    job.run().join()

    assert sleep_delays == [60, 120, 240, 480]
    assert heating.refresh.call_count == 5

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 5
    assert all(run.status == "failure" for run in runs)
    assert all(run.error_message == "Hive backend unreachable" for run in runs)


def test_run_pending_safely_does_not_propagate_a_scheduled_job_failure() -> None:
    scheduler = Mock(spec=Scheduler)
    scheduler.run_pending.side_effect = RuntimeError("boom")

    run_pending_safely(scheduler)

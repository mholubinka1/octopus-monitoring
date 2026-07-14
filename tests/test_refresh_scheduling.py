from unittest.mock import Mock

import pytest
from common.config import RefreshSettings
from data.consumption import ConsumptionRetriever
from data.mysql import sql_models
from data.mysql.client import MariaDBClient
from main import register_jobs, run_pending_safely
from schedule import Scheduler

REFRESH_CONFIG = RefreshSettings(
    {
        "data_refresh": {
            "polling_interval_seconds": 1,
            "refresh_interval_hours": 4,
            "historical_limit_days": 45,
        }
    }
)


def test_registered_job_runs_on_the_configured_refresh_interval(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()

    job = register_jobs(
        scheduler, REFRESH_CONFIG, Mock(spec=ConsumptionRetriever), mariadb_client
    )

    assert job.interval == REFRESH_CONFIG.refresh_interval
    assert job.unit == "hours"


def test_successful_refresh_is_recorded_as_a_successful_job_run(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    consumption = Mock(spec=ConsumptionRetriever)

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)
    job.run()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(sql_models.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "consumption_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_failed_refresh_is_recorded_as_a_failed_job_run_and_still_raises(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    consumption = Mock(spec=ConsumptionRetriever)
    consumption.refresh.side_effect = RuntimeError("Octopus API unavailable")

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)

    with pytest.raises(RuntimeError, match="Octopus API unavailable"):
        job.run()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(sql_models.job_run).all()

    assert len(runs) == 1
    assert runs[0].status == "failure"
    assert runs[0].error_message == "Octopus API unavailable"


def test_run_pending_safely_does_not_propagate_a_scheduled_job_failure() -> None:
    scheduler = Mock(spec=Scheduler)
    scheduler.run_pending.side_effect = RuntimeError("boom")

    run_pending_safely(scheduler)

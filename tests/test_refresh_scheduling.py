import threading
from unittest.mock import Mock

import pytest
from common.config import RefreshSettings
from data.consumption import ConsumptionRetriever
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.pricing import PricingRetriever
from main import (
    register_jobs,
    register_pricing_job,
    run_initial_pricing_sync,
    run_pending_safely,
)
from schedule import Scheduler

REFRESH_CONFIG = RefreshSettings(refresh_interval=4, retention=45)


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
    worker = job.run()
    worker.join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "consumption_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_persistently_failing_refresh_retries_with_exponential_backoff(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_delays: list = []
    monkeypatch.setattr("common.decorator.time.sleep", sleep_delays.append)
    scheduler = Scheduler()
    consumption = Mock(spec=ConsumptionRetriever)
    consumption.refresh.side_effect = RuntimeError("Octopus API unavailable")

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)
    job.run().join()

    assert sleep_delays == [60, 120, 240, 480]
    assert consumption.refresh.call_count == 5

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 5
    assert all(run.status == "failure" for run in runs)
    assert all(run.error_message == "Octopus API unavailable" for run in runs)


def test_a_second_invocation_is_skipped_while_a_worker_is_already_running(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    consumption = Mock(spec=ConsumptionRetriever)
    started = threading.Event()
    release = threading.Event()

    def slow_refresh() -> None:
        started.set()
        release.wait(timeout=5)

    consumption.refresh.side_effect = slow_refresh

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)
    first_worker = job.run()
    started.wait(timeout=5)

    second_worker = job.run()

    release.set()
    first_worker.join()

    assert second_worker is first_worker
    assert consumption.refresh.call_count == 1


def test_a_new_invocation_after_the_worker_finished_starts_a_fresh_attempt_count(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    scheduler = Scheduler()
    consumption = Mock(spec=ConsumptionRetriever)
    consumption.refresh.side_effect = RuntimeError("Octopus API unavailable")

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)
    job.run().join()

    consumption.refresh.side_effect = None
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).order_by(model.job_run.ran_at).all()

    assert [run.status for run in runs] == ["failure"] * 5 + ["success"]


def test_pricing_job_runs_on_the_configured_interval_and_records_its_outcome(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    pricing = Mock(spec=PricingRetriever)

    job = register_pricing_job(scheduler, REFRESH_CONFIG, pricing, mariadb_client)

    assert job.interval == REFRESH_CONFIG.refresh_interval
    assert job.unit == "hours"

    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "pricing_refresh"
    assert runs[0].status == "success"


def test_run_pending_safely_does_not_propagate_a_scheduled_job_failure() -> None:
    scheduler = Mock(spec=Scheduler)
    scheduler.run_pending.side_effect = RuntimeError("boom")

    run_pending_safely(scheduler)


def test_run_initial_pricing_sync_does_not_propagate_a_startup_failure() -> None:
    pricing = Mock(spec=PricingRetriever)
    pricing.refresh.side_effect = RuntimeError("Octopus API unavailable")

    run_initial_pricing_sync(pricing)

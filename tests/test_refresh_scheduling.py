import threading
from unittest.mock import Mock

import pytest
from common.config import RefreshSettings
from data.consumption import ConsumptionRetriever
from data.consumption_summary import (
    ConsumptionSummaryBackfill,
    ConsumptionSummaryRetriever,
)
from data.cost_forecast import CostForecastRetriever
from data.mysql import model
from data.mysql.client import MariaDBClient
from data.pricing import PricingRetriever
from main import (
    register_consumption_summary_job,
    register_cost_forecast_refresh_job,
    register_jobs,
    register_pricing_job,
    run_backfill_at_startup,
    run_initial_consumption_summary_sync,
    run_initial_cost_forecast_sync,
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
    sleep_delays: list[int] = []
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
    released_in_time: list[bool] = []

    def slow_refresh() -> None:
        started.set()
        released_in_time.append(release.wait(timeout=5))

    consumption.refresh.side_effect = slow_refresh

    job = register_jobs(scheduler, REFRESH_CONFIG, consumption, mariadb_client)
    first_worker = job.run()
    assert started.wait(timeout=5), "worker did not start within timeout"

    second_worker = job.run()

    release.set()
    first_worker.join()

    assert released_in_time == [True], "worker did not observe release within timeout"
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


def test_consumption_summary_job_is_registered_for_monday_at_0300(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()

    job = register_consumption_summary_job(
        scheduler, Mock(spec=ConsumptionSummaryRetriever), mariadb_client
    )

    assert job.unit == "weeks"
    assert job.start_day == "monday"
    assert str(job.at_time) == "03:00:00"


def test_a_successful_consumption_summary_run_is_recorded_as_a_successful_job_run(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    consumption_summary = Mock(spec=ConsumptionSummaryRetriever)

    job = register_consumption_summary_job(
        scheduler, consumption_summary, mariadb_client
    )
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "update_consumption_summary"
    assert runs[0].status == "success"


def test_a_persistently_failing_consumption_summary_run_retries_with_backoff(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_delays: list[int] = []
    monkeypatch.setattr("common.decorator.time.sleep", sleep_delays.append)
    scheduler = Scheduler()
    consumption_summary = Mock(spec=ConsumptionSummaryRetriever)
    consumption_summary.refresh.side_effect = RuntimeError("MariaDB unavailable")

    job = register_consumption_summary_job(
        scheduler, consumption_summary, mariadb_client
    )
    job.run().join()

    assert sleep_delays == [60, 120, 240, 480]
    assert consumption_summary.refresh.call_count == 5

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 5
    assert all(run.status == "failure" for run in runs)
    assert all(run.error_message == "MariaDB unavailable" for run in runs)


def test_run_initial_consumption_summary_sync_does_not_propagate_a_startup_failure() -> (
    None
):
    consumption_summary = Mock(spec=ConsumptionSummaryRetriever)
    consumption_summary.refresh.side_effect = RuntimeError("MariaDB unavailable")

    run_initial_consumption_summary_sync(consumption_summary)


def test_run_initial_cost_forecast_sync_does_not_propagate_a_startup_failure() -> None:
    cost_forecast = Mock(spec=CostForecastRetriever)
    cost_forecast.refresh.side_effect = RuntimeError("Kraken unavailable")

    run_initial_cost_forecast_sync(cost_forecast)


def test_cost_forecast_refresh_job_is_registered_daily_at_0400(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()

    job = register_cost_forecast_refresh_job(
        scheduler, Mock(spec=CostForecastRetriever), mariadb_client
    )

    assert job.unit == "days"
    assert str(job.at_time) == "04:00:00"


def test_a_successful_cost_forecast_run_is_recorded_as_a_successful_job_run(
    mariadb_client: MariaDBClient,
) -> None:
    scheduler = Scheduler()
    cost_forecast = Mock(spec=CostForecastRetriever)

    job = register_cost_forecast_refresh_job(scheduler, cost_forecast, mariadb_client)
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "cost_forecast_refresh"
    assert runs[0].status == "success"


def test_a_failed_cost_forecast_run_is_recorded_as_a_failed_job_run_and_no_row_left_dangling(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    scheduler = Scheduler()
    cost_forecast = Mock(spec=CostForecastRetriever)
    cost_forecast.refresh.side_effect = RuntimeError("Kraken unavailable")

    job = register_cost_forecast_refresh_job(scheduler, cost_forecast, mariadb_client)
    job.run().join()

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert all(run.status == "failure" for run in runs)
    assert len(runs) > 0


def test_backfill_runs_and_records_success_on_first_startup(
    mariadb_client: MariaDBClient,
) -> None:
    backfill = Mock(spec=ConsumptionSummaryBackfill)

    worker = run_backfill_at_startup(backfill, mariadb_client)
    assert worker is not None
    worker.join()

    backfill.run.assert_called_once()
    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()
    assert len(runs) == 1
    assert runs[0].job_name == "yearly_comparison_backfill"
    assert runs[0].status == "success"


def test_backfill_is_skipped_once_a_prior_run_has_succeeded(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.record_job_run("yearly_comparison_backfill", "success")
    backfill = Mock(spec=ConsumptionSummaryBackfill)

    worker = run_backfill_at_startup(backfill, mariadb_client)

    assert worker is None
    backfill.run.assert_not_called()


def test_a_persistently_failing_backfill_retries_with_backoff_and_does_not_crash(
    mariadb_client: MariaDBClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_delays: list[int] = []
    monkeypatch.setattr("common.decorator.time.sleep", sleep_delays.append)
    backfill = Mock(spec=ConsumptionSummaryBackfill)
    backfill.run.side_effect = RuntimeError("Octopus API unavailable")

    worker = run_backfill_at_startup(backfill, mariadb_client)
    assert worker is not None
    worker.join()

    assert sleep_delays == [60, 120, 240, 480]
    assert backfill.run.call_count == 5

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()
    assert len(runs) == 5
    assert all(run.status == "failure" for run in runs)

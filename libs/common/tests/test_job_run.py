from libs.common.common.mariadb.client import MariaDBClientBase
from libs.common.common.mariadb.model import job_run


def test_has_successful_job_run_is_false_when_no_run_has_ever_been_recorded(
    mariadb_client: MariaDBClientBase,
) -> None:
    assert mariadb_client.has_successful_job_run("consumption_refresh") is False


def test_has_successful_job_run_is_true_once_a_success_has_been_recorded(
    mariadb_client: MariaDBClientBase,
) -> None:
    mariadb_client.record_job_run("consumption_refresh", "success")

    assert mariadb_client.has_successful_job_run("consumption_refresh") is True


def test_latest_job_run_is_successful_reflects_the_most_recent_run_not_an_earlier_one(
    mariadb_client: MariaDBClientBase,
) -> None:
    mariadb_client.record_job_run("update_consumption_summary", "success")
    mariadb_client.record_job_run("update_consumption_summary", "failure", error="boom")

    assert (
        mariadb_client.latest_job_run_is_successful("update_consumption_summary")
        is False
    )


def test_record_job_run_persists_a_successful_outcome(
    mariadb_client: MariaDBClientBase,
) -> None:
    mariadb_client.record_job_run("consumption_refresh", "success")

    with mariadb_client.session_read_scope() as session:
        runs = session.query(job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "consumption_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_record_job_run_persists_a_failure_outcome_with_its_error_message(
    mariadb_client: MariaDBClientBase,
) -> None:
    mariadb_client.record_job_run("consumption_refresh", "failure", error="API timeout")

    with mariadb_client.session_read_scope() as session:
        runs = session.query(job_run).all()

    assert len(runs) == 1
    assert runs[0].status == "failure"
    assert runs[0].error_message == "API timeout"

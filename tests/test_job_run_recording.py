from data.mysql import model
from data.mysql.client import MariaDBClient


def test_record_job_run_persists_a_successful_outcome(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.record_job_run("consumption_refresh", "success")

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].job_name == "consumption_refresh"
    assert runs[0].status == "success"
    assert runs[0].error_message is None


def test_record_job_run_persists_a_failure_outcome_with_its_error_message(
    mariadb_client: MariaDBClient,
) -> None:
    mariadb_client.record_job_run("consumption_refresh", "failure", error="API timeout")

    with mariadb_client.session_read_scope() as session:
        runs = session.query(model.job_run).all()

    assert len(runs) == 1
    assert runs[0].status == "failure"
    assert runs[0].error_message == "API timeout"

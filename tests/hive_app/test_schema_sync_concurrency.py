from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from hive_app.common.config import MariaDBSettings
from hive_app.data.mysql.client import MariaDBClient, _is_table_already_exists_error
from hive_app.data.mysql.model import SQLBase


def _mysql_error(code: int, message: str) -> OperationalError:
    orig = Mock()
    orig.args = (code, message)
    return OperationalError("<statement>", {}, orig)


def test_is_table_already_exists_error_matches_mysql_error_1050() -> None:
    error = _mysql_error(1050, "Table 'octopus.job_run' already exists")

    assert _is_table_already_exists_error(error) is True


def test_is_table_already_exists_error_does_not_match_unrelated_errors() -> None:
    error = _mysql_error(2003, "Can't connect to MySQL server")

    assert _is_table_already_exists_error(error) is False


def _sqlite_settings() -> MariaDBSettings:
    return MariaDBSettings(
        host="localhost",
        port=3306,
        database="octopus",
        username="test",
        password="test",
    )


def test_schema_sync_recovers_from_a_concurrent_table_creation_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given app/ and hive_app/ start against a freshly-initialized database
    at the same moment, both can see the shared job_run table as absent and
    race to create it -- the loser's CREATE TABLE fails "already exists".
    Constructing MariaDBClient (its public interface) must still succeed,
    recovering via a single retry, rather than crashing the container."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"octopus": None})
    monkeypatch.setattr(
        "hive_app.data.mysql.client.create_engine", lambda *args, **kwargs: engine
    )

    real_create_all = SQLBase.metadata.create_all
    attempts: list[int] = []

    def flaky_create_all(bind: Engine, checkfirst: bool = True) -> None:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise _mysql_error(1050, "Table 'octopus.job_run' already exists")
        real_create_all(bind, checkfirst=checkfirst)

    monkeypatch.setattr(
        "hive_app.data.mysql.client.SQLBase.metadata.create_all", flaky_create_all
    )

    MariaDBClient(_sqlite_settings())

    assert attempts == [1, 2]


def test_schema_sync_does_not_swallow_an_unrelated_schema_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"octopus": None})
    monkeypatch.setattr(
        "hive_app.data.mysql.client.create_engine", lambda *args, **kwargs: engine
    )

    def failing_create_all(*args: object, **kwargs: object) -> None:
        raise _mysql_error(1046, "No database selected")

    monkeypatch.setattr(
        "hive_app.data.mysql.client.SQLBase.metadata.create_all", failing_create_all
    )

    with pytest.raises(OperationalError):
        MariaDBClient(_sqlite_settings())

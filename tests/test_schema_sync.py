import pytest
from common.config import MariaDBSettings
from data.mysql.client import MariaDBClient
from data.mysql.sql_models import SQLBase
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


def _sqlite_engine() -> Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"octopus": None})


def _settings() -> MariaDBSettings:
    return MariaDBSettings(
        host="localhost",
        port=3306,
        database="octopus",
        username="test",
        password="test",
    )


def test_a_table_missing_from_the_database_is_created_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _sqlite_engine()
    tables_except_job_run = [
        table for table in SQLBase.metadata.tables.values() if table.name != "job_run"
    ]
    SQLBase.metadata.create_all(engine, tables=tables_except_job_run)
    monkeypatch.setattr(
        "data.mysql.client.create_engine", lambda *args, **kwargs: engine
    )

    MariaDBClient(_settings())

    columns = {column["name"] for column in inspect(engine).get_columns("job_run")}
    assert columns == {"id", "job_name", "status", "ran_at", "error_message"}


def test_a_database_with_every_table_already_present_is_left_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _sqlite_engine()
    SQLBase.metadata.create_all(engine)
    monkeypatch.setattr(
        "data.mysql.client.create_engine", lambda *args, **kwargs: engine
    )

    MariaDBClient(_settings())

    table_names = set(inspect(engine).get_table_names())
    assert table_names == {table.name for table in SQLBase.metadata.tables.values()}

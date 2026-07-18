import pytest
from common.config import MariaDBSettings
from data.mysql.client import MariaDBClient
from data.mysql.sql_models import SQLBase
from sqlalchemy import Column, DateTime, Float, String, create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

_StrippedBase = declarative_base()


class _StrippedConsumption(_StrippedBase):
    __tablename__ = "consumption"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    energy = Column(String)
    period_from = Column(DateTime, nullable=False)
    period_to = Column(DateTime, nullable=False)
    raw_value = Column(Float, nullable=False)
    est_kwh = Column(Float, nullable=False)


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


def _sync_against(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> MariaDBClient:
    monkeypatch.setattr(
        "data.mysql.client.create_engine", lambda *args, **kwargs: engine
    )
    return MariaDBClient(_settings())


def test_a_table_missing_from_the_database_is_created_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _sqlite_engine()
    tables_except_job_run = [
        table for table in SQLBase.metadata.tables.values() if table.name != "job_run"
    ]
    SQLBase.metadata.create_all(engine, tables=tables_except_job_run)

    _sync_against(engine, monkeypatch)

    columns = {column["name"] for column in inspect(engine).get_columns("job_run")}
    assert columns == {"id", "job_name", "status", "ran_at", "error_message"}


def test_a_database_with_every_table_already_present_is_left_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _sqlite_engine()
    SQLBase.metadata.create_all(engine)

    _sync_against(engine, monkeypatch)

    table_names = set(inspect(engine).get_table_names())
    assert table_names == {table.name for table in SQLBase.metadata.tables.values()}


def test_a_column_missing_from_an_existing_table_is_added_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _sqlite_engine()
    _StrippedBase.metadata.create_all(engine)

    _sync_against(engine, monkeypatch)

    columns = {column["name"] for column in inspect(engine).get_columns("consumption")}
    assert columns == {
        "id",
        "energy",
        "period_from",
        "period_to",
        "raw_value",
        "unit",
        "est_kwh",
    }


def test_every_declared_table_compiles_as_valid_mariadb_ddl() -> None:
    for table in SQLBase.metadata.tables.values():
        CreateTable(table).compile(dialect=mysql.dialect())

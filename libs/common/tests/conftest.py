import logging

import pytest
from common.config import MariaDBSettings
from common.mariadb.client import MariaDBClientBase
from common.mariadb.model import SQLBase
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def mariadb_client(monkeypatch: pytest.MonkeyPatch) -> MariaDBClientBase:
    """A MariaDBClientBase backed by an in-memory SQLite database.

    job_run is declared with schema="octopus" for real MariaDB, which SQLite
    has no equivalent for, so the schema is translated away for this engine.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"octopus": None})

    monkeypatch.setattr(
        "common.mariadb.client.create_engine",
        lambda *args, **kwargs: engine,
    )

    settings = MariaDBSettings(
        host="localhost",
        port=3306,
        database="octopus",
        username="test",
        password="test",
    )
    return MariaDBClientBase(
        settings, declarative_base=SQLBase, logger=logging.getLogger("test")
    )

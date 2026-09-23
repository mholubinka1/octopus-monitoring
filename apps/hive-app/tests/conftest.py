import pytest
from hive_app.data.mysql.client import MariaDBClient
from hive_app.data.mysql.model import SQLBase
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from libs.common.common.config import MariaDBSettings


@pytest.fixture
def mariadb_client(monkeypatch: pytest.MonkeyPatch) -> MariaDBClient:
    """A hive_app MariaDBClient backed by an in-memory SQLite database.

    Tables are declared with schema="octopus" for real MariaDB, which SQLite
    has no equivalent for, so the schema is translated away for this engine.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"octopus": None})
    SQLBase.metadata.create_all(engine)

    monkeypatch.setattr(
        "libs.common.common.mariadb.client.create_engine",
        lambda *args, **kwargs: engine,
    )

    settings = MariaDBSettings(
        host="localhost",
        port=3306,
        database="octopus",
        username="test",
        password="test",
    )
    return MariaDBClient(settings)

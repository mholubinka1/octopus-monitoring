import logging.config
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from logging import Logger, getLogger
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateColumn

from hive_app.common.config import MariaDBSettings
from hive_app.common.exceptions import MariaDBError
from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus
from hive_app.data.mysql import model as sql_model
from hive_app.data.mysql.model import SQLBase

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

# MySQL/MariaDB error 1050: "Table '...' already exists".
_TABLE_ALREADY_EXISTS_ERROR_CODE = 1050


def _is_table_already_exists_error(exc: OperationalError | ProgrammingError) -> bool:
    orig_args: tuple[object, ...] = getattr(exc.orig, "args", ())
    return bool(orig_args) and orig_args[0] == _TABLE_ALREADY_EXISTS_ERROR_CODE


def upsert(s: Session, record: Any) -> None:
    try:
        with s.begin_nested():
            s.add(record)
            s.flush()
            return
    except IntegrityError as exc:
        pk_columns = [col.name for col in inspect(type(record)).primary_key]
        pk_filter = {col: getattr(record, col) for col in pk_columns}
        update_dict = {
            col.name: getattr(record, col.name) for col in record.__table__.columns
        }
        if (
            s.query(type(record))
            .filter_by(**pk_filter)
            .update(update_dict, synchronize_session=False)
        ):
            return
        raise RuntimeError(
            f"Upsert conflict resolution failed: no {type(record).__name__} row "
            f"matched primary key {pk_filter}. The IntegrityError was likely caused "
            "by a non-primary-key constraint violation."
        ) from exc


class SessionBuilder:
    session: sessionmaker
    engine: Engine

    def __init__(self, settings: MariaDBSettings):
        uri = f"mysql+pymysql://{settings.username}:{settings.password}@{settings.host}:{settings.port}/{settings.database}"
        self.engine = create_engine(uri)
        self.session = sessionmaker(bind=self.engine)


class MariaDBClient:
    def __init__(self, settings: MariaDBSettings) -> None:
        self._session_builder = SessionBuilder(settings)
        self._sync_schema()

    def _sync_schema(self) -> None:
        engine = self._session_builder.engine
        existing_tables = set(inspect(engine).get_table_names())

        self._create_all_tolerating_concurrent_creation(engine)

        created_tables = {
            table.name for table in SQLBase.metadata.tables.values()
        } - existing_tables
        if created_tables:
            logger.info(
                f"Schema sync: created missing tables: {sorted(created_tables)}"
            )

        inspector = inspect(engine)
        with engine.begin() as connection:
            self._sync_missing_columns(connection, inspector)

    @staticmethod
    def _create_all_tolerating_concurrent_creation(engine: Engine) -> None:
        """create_all's own checkfirst existence check and the CREATE TABLE
        statement it issues aren't atomic -- if app/ and hive_app/ (which
        share octopus.job_run, see the job_run model's own comment) both
        start against a freshly-initialized database at the same time, both
        can see that table as absent and race to create it, with the
        loser's CREATE TABLE failing "table already exists". Retrying once
        (checkfirst now sees the winner's table and skips it) recovers from
        exactly that race without weakening the check for a genuine schema
        problem, which would fail identically on the retry too.

        app/data/mysql/client.py carries an identical copy of this method
        and _is_table_already_exists_error (the two packages' schema-sync
        logic is deliberately independent, see job_run's own comment) --
        keep both in sync if this retry logic is ever extended, e.g. to
        tolerate another error code."""
        try:
            SQLBase.metadata.create_all(engine, checkfirst=True)
        except (OperationalError, ProgrammingError) as e:
            if not _is_table_already_exists_error(e):
                raise
            logger.info(
                "Schema sync: table creation raced with another process "
                "(e.g. app/hive_app starting concurrently) -- retrying now "
                "that the table exists."
            )
            SQLBase.metadata.create_all(engine, checkfirst=True)

    def _sync_missing_columns(
        self, connection: Connection, inspector: Inspector
    ) -> None:
        for table in SQLBase.metadata.tables.values():
            schema = connection.schema_for_object(table)
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table.name, schema=schema)
            }
            missing_columns = [
                column
                for column in table.columns
                if column.name not in existing_columns
            ]
            if not missing_columns:
                continue

            logger.info(
                f"Schema sync: adding missing columns to {table.name}: "
                f"{[column.name for column in missing_columns]}"
            )

            qualified_name = f"{schema}.{table.name}" if schema else table.name
            for column in missing_columns:
                column_ddl = CreateColumn(column).compile(dialect=connection.dialect)
                connection.execute(
                    text(f"ALTER TABLE {qualified_name} ADD COLUMN {column_ddl}")
                )

    @contextmanager
    def session_read_scope(self) -> Generator[Session]:
        session = self._session_builder.session()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def session_write_scope(self) -> Generator[Session]:
        session = self._session_builder.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _write_all(self, records: list[Any], description: str) -> None:
        try:
            with self.session_write_scope() as s:
                for record in records:
                    upsert(s, record)
                logger.debug(f"{description}: {len(records)} written to MariaDB.")
                return
        except Exception as e:
            logger.error(f"Failed to write {description}: {e}")
            raise MariaDBError(e) from e

    def write_heating_status(self, status: HeatingStatus) -> None:
        # sqlalchemy-stubs models every Numeric subclass (Float included) as
        # TypeEngine[Decimal], so it reports a float/Decimal mismatch here even
        # though SQLAlchemy's real runtime Float column stores/returns a plain
        # Python float -- a known stub-accuracy gap, not a real type error.
        record = sql_model.heating_status(
            polled_at=status.polled_at,
            current_temp=status.current_temp,  # type: ignore[misc]
            target_temp=status.target_temp,  # type: ignore[misc]
            mode=status.mode,
            state=status.state,
            boost_active=status.boost_active,
            boost_ends_at=status.boost_ends_at,
            schedule=status.schedule,
        )
        self._write_all([record], "Heating status data")

    def record_job_run(
        self, job_name: str, status: str, error: str | None = None
    ) -> None:
        try:
            with self.session_write_scope() as s:
                record = sql_model.job_run(
                    job_name=job_name,
                    status=status,
                    ran_at=datetime.now(UTC),
                    error_message=error,
                )
                s.add(record)
                logger.debug(f"Recorded job run: {job_name} ({status}).")
                return
        except Exception as e:
            logger.error(f"Failed to record job run for {job_name}: {e}")
            raise MariaDBError(e) from e

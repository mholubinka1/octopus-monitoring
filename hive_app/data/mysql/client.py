import logging.config
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from logging import Logger, getLogger
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateColumn

from hive_app.common.config import MariaDBSettings
from hive_app.common.exceptions import MariaDBError
from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus, HiveAuthState
from hive_app.data.mysql import model as sql_model
from hive_app.data.mysql.model import SQLBase

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

# hive_auth_state is a single-row, upserted table (see ADR context in the
# spec's "Auth state" section) -- every write targets this same fixed id
# rather than accumulating a row per login/refresh.
HIVE_AUTH_STATE_ID = 1


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

        SQLBase.metadata.create_all(engine, checkfirst=True)

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

    def write_hive_auth_state(self, state: HiveAuthState) -> None:
        record = sql_model.hive_auth_state(
            id=HIVE_AUTH_STATE_ID,
            refresh_token=state.refresh_token,
            device_group_key=state.device_group_key,
            device_key=state.device_key,
            updated_at=state.updated_at,
        )
        self._write_all([record], "Hive auth state")

    def read_hive_auth_state(self) -> HiveAuthState | None:
        with self.session_read_scope() as session:
            row = (
                session.query(sql_model.hive_auth_state)
                .filter_by(id=HIVE_AUTH_STATE_ID)
                .first()
            )
        if row is None:
            return None
        # DATETIME columns come back tz-naive regardless of backend -- every
        # value stored here is UTC by convention (see read_agile_forecast's
        # identical reattachment in app/data/mysql/client.py), so it's
        # reattached here rather than left for callers to guess.
        return HiveAuthState(
            refresh_token=row.refresh_token,
            device_group_key=row.device_group_key,
            device_key=row.device_key,
            updated_at=row.updated_at.replace(tzinfo=UTC),
        )

    def has_successful_job_run(self, job_name: str) -> bool:
        with self.session_read_scope() as session:
            return (
                session.query(sql_model.job_run)
                .filter_by(job_name=job_name, status="success")
                .first()
                is not None
            )

    def latest_job_run_is_successful(self, job_name: str) -> bool:
        with self.session_read_scope() as session:
            latest = (
                session.query(sql_model.job_run)
                .filter_by(job_name=job_name)
                .order_by(sql_model.job_run.ran_at.desc(), sql_model.job_run.id.desc())
                .first()
            )
            return latest is not None and latest.status == "success"

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

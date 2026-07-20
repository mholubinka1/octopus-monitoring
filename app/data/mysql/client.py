import logging.config
from contextlib import contextmanager
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Generator, List, Optional

from common.config import MariaDBSettings
from common.exceptions import MariaDBError
from common.logging import APP_LOGGER_NAME, config
from data.model import Consumption, as_energy_char
from data.mysql import model
from data.mysql.model import SQLBase
from data.octopus.model import Agreement, Meter, Product, Rate
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateColumn

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


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
    except Exception as e:
        raise e


def _energy_scoped_id(energy_char: str, dt: datetime) -> str:
    return energy_char + dt.strftime("%Y%m%d%H%M%S")


def _rate_scoped_id(product_code: str, region: str, valid_from: datetime) -> str:
    return f"{product_code}_{region}_{valid_from.strftime('%Y%m%d%H%M')}"


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
        # MariaDB/MySQL DDL auto-commits per statement, so this transaction
        # doesn't make the ADD COLUMN loop atomic — it's just a connection
        # scope. Idempotent regardless: a re-run picks up anything not yet added.
        with engine.begin() as connection:
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
                    column_ddl = CreateColumn(column).compile(dialect=engine.dialect)
                    connection.execute(
                        text(f"ALTER TABLE {qualified_name} ADD COLUMN {column_ddl}")
                    )

    @contextmanager
    def session_read_scope(self) -> Generator[Session, None, None]:
        session = self._session_builder.session()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def session_write_scope(self) -> Generator[Session, None, None]:
        session = self._session_builder.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _write_all(self, records: List[Any], description: str) -> None:
        try:
            with self.session_write_scope() as s:
                for record in records:
                    upsert(s, record)
                logger.debug(f"{description}: {len(records)} written to MariaDB.")
                return
        except Exception as e:
            logger.error(f"Failed to write {description}: {e}")
            raise MariaDBError(e) from e

    def write_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        energy_char = as_energy_char(meter.energy)
        records = [
            model.consumption(
                id=_energy_scoped_id(energy_char, point.start),
                energy=energy_char,
                period_from=point.start,
                period_to=point.end,
                raw_value=point.raw,
                unit=point.unit.name,
                est_kwh=point.est_kwh,
            )
            for point in consumption
        ]
        self._write_all(records, "Consumption data")

    def write_agreement(self, meter: Meter, agreements: List[Agreement]) -> None:
        energy_char = as_energy_char(meter.energy)
        records = [
            model.agreement(
                id=_energy_scoped_id(energy_char, agreement.valid_from),
                energy=energy_char,
                product_code=agreement.product_code,
                tariff_code=agreement.tariff_code,
                valid_from=agreement.valid_from,
                valid_to=agreement.valid_to,
            )
            for agreement in agreements
        ]
        self._write_all(records, "Agreement data")

    def write_product(self, product: Product) -> None:
        record = model.product(
            product_code=product.product_code,
            display_name=product.display_name,
            direction=product.direction.value,
        )
        self._write_all([record], "Product data")

    def write_product_rate(
        self, product_code: str, region: str, rates: List[Rate]
    ) -> None:
        records = [
            model.product_rate(
                id=_rate_scoped_id(product_code, region, rate.valid_from),
                product_code=product_code,
                region=region,
                valid_from=rate.valid_from,
                valid_to=rate.valid_to,
                unit_rate=rate.unit_rate,
                standing_charge=rate.standing_charge,
            )
            for rate in rates
        ]
        self._write_all(records, "Product rate data")

    def record_job_run(
        self, job_name: str, status: str, error: Optional[str] = None
    ) -> None:
        try:
            with self.session_write_scope() as s:
                record = model.job_run(
                    job_name=job_name,
                    status=status,
                    ran_at=datetime.now(timezone.utc),
                    error_message=error,
                )
                s.add(record)
                logger.debug(f"Recorded job run: {job_name} ({status}).")
                return
        except Exception as e:
            logger.error(f"Failed to record job run for {job_name}: {e}")
            raise MariaDBError(e) from e

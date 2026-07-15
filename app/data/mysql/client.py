import logging.config
from contextlib import contextmanager
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Generator, List, Optional

from common.config import MariaDBSettings
from common.decorator import retry
from common.exceptions import MariaDBError
from common.logging import APP_LOGGER_NAME, config
from data.model import Consumption, as_energy_char
from data.mysql import sql_models
from data.octopus.model import Agreement, Meter
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


@retry()
def upsert(s: Session, record: Any) -> None:
    try:
        with s.begin_nested():
            s.add(record)
            s.flush()
            return
    except IntegrityError:
        update_dict = {
            col.name: getattr(record, col.name) for col in record.__table__.columns
        }
        if (
            s.query(type(record))
            .filter_by(id=record.id)
            .update(update_dict, synchronize_session=False)
        ):
            return
    except Exception as e:
        raise e


class SessionBuilder:
    session: sessionmaker

    def __init__(self, settings: MariaDBSettings):
        uri = f"mysql+pymysql://{settings.username}:{settings.password}@{settings.host}:{settings.port}/{settings.database}"
        engine = create_engine(uri)
        self.session = sessionmaker(bind=engine)


class MariaDBClient:
    def __init__(self, settings: MariaDBSettings) -> None:
        self._session_builder = SessionBuilder(settings)

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

    def write_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        try:
            with self.session_write_scope() as s:
                for point in consumption:
                    energy_char = as_energy_char(meter.energy)
                    record_id = energy_char + point.start.strftime("%Y%m%d%H%M%S")
                    record = sql_models.consumption(
                        id=record_id,
                        energy=energy_char,
                        period_from=point.start,
                        period_to=point.end,
                        raw_value=point.raw,
                        unit=point.unit.name,
                        est_kwh=point.est_kwh,
                    )
                    upsert(s, record)
                logger.debug(
                    f"Consumption data written to MariaDB: {len(consumption)} points."
                )
                return
        except Exception as e:
            logger.error(f"Failed to write consumption data: {e}")
            raise MariaDBError(e) from e

    def write_agreement(self, meter: Meter, agreements: List[Agreement]) -> None:
        try:
            with self.session_write_scope() as s:
                for agreement in agreements:
                    energy_char = as_energy_char(meter.energy)
                    record_id = energy_char + agreement.valid_from.strftime(
                        "%Y%m%d%H%M%S"
                    )
                    record = sql_models.agreement(
                        id=record_id,
                        energy=energy_char,
                        product_code=agreement.product_code,
                        tariff_code=agreement.tariff_code,
                        valid_from=agreement.valid_from,
                        valid_to=agreement.valid_to,
                    )
                    upsert(s, record)
                logger.debug(
                    f"Agreement data written to MariaDB: {len(agreements)} agreements."
                )
                return
        except Exception as e:
            logger.error(f"Failed to write agreement data: {e}")
            raise MariaDBError(e) from e

    def record_job_run(
        self, job_name: str, status: str, error: Optional[str] = None
    ) -> None:
        try:
            with self.session_write_scope() as s:
                record = sql_models.job_run(
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

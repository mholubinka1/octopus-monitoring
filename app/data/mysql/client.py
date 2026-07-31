import logging.config
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any

from common.config import MariaDBSettings
from common.exceptions import MariaDBError
from common.logging import APP_LOGGER_NAME, config
from data import local_day
from data.model import (
    Consumption,
    ConsumptionSummary,
    CostForecast,
    DailyCostSummary,
    Energy,
    as_energy_char,
    energy_from_char,
)
from data.mysql import model
from data.mysql.model import SQLBase
from data.octopus.model import AgileForecastReading, Agreement, Meter, Product, Rate
from sqlalchemy import and_, create_engine, inspect, or_, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateColumn

SUMMARIZATION_WINDOW_DAYS = 14

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


@dataclass
class _DailyAccumulator:
    total_kwh: Decimal = Decimal(0)
    variable_cost: Decimal = Decimal(0)
    standing_charge: Decimal = Decimal(0)
    row_count: int = 0


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


def _energy_scoped_id(energy_char: str, dt: datetime) -> str:
    return energy_char + dt.strftime("%Y%m%d%H%M%S")


def _rate_scoped_id(product_code: str, region: str, valid_from: datetime) -> str:
    return f"{product_code}_{region}_{valid_from.strftime('%Y%m%d%H%M')}"


def _forecast_scoped_id(region: str, period_from: datetime) -> str:
    return f"{region}_{period_from.strftime('%Y%m%d%H%M')}"


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
            self._sync_missing_columns(connection, inspector)
            self._sync_missing_indexes(connection, inspector)

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

    def _sync_missing_indexes(
        self, connection: Connection, inspector: Inspector
    ) -> None:
        for table in SQLBase.metadata.tables.values():
            schema = connection.schema_for_object(table)
            existing_index_names = {
                index["name"]
                for index in inspector.get_indexes(table.name, schema=schema)
            }
            missing_indexes = [
                index
                for index in table.indexes
                if index.name not in existing_index_names
            ]
            if not missing_indexes:
                continue

            logger.info(
                f"Schema sync: creating missing indexes on {table.name}: "
                f"{[index.name for index in missing_indexes]}"
            )
            for index in missing_indexes:
                index.create(bind=connection)

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

    def write_consumption(self, meter: Meter, consumption: list[Consumption]) -> None:
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

    def write_agreement(self, meter: Meter, agreements: list[Agreement]) -> None:
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
        self, product_code: str, region: str, rates: list[Rate]
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

    def write_agile_forecast(
        self,
        region: str,
        readings: list[AgileForecastReading],
        fetched_at: datetime,
    ) -> None:
        records = [
            model.agile_forecast(
                id=_forecast_scoped_id(region, reading.period_from),
                region=region,
                period_from=reading.period_from,
                period_to=reading.period_to,
                forecast_unit_rate=reading.unit_rate,
                fetched_at=fetched_at,
            )
            for reading in readings
        ]
        self._write_all(records, "Agile forecast data")

    def write_cost_forecast(self, forecast: CostForecast) -> None:
        record = model.cost_forecast(
            billing_period_start=forecast.billing_period_start,
            billing_period_end=forecast.billing_period_end,
            actual_cost_to_date=forecast.actual_cost_to_date,
            projected_total_cost=forecast.projected_total_cost,
            computed_at=forecast.computed_at,
        )
        self._write_all([record], "Cost forecast data")

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Rate | None:
        pr = model.product_rate
        with self.session_read_scope() as session:
            row = (
                session.query(pr)
                .filter(
                    pr.product_code == product_code,
                    pr.region == region,
                    pr.valid_from <= as_of,
                    or_(pr.valid_to.is_(None), as_of < pr.valid_to),
                )
                # Explicit ordering, not bare .first(): if overlapping rows
                # ever matched (bad upstream data), .first() with no ORDER
                # BY is nondeterministic. Most-recently-started wins, same
                # "ORDER BY valid_from DESC LIMIT 1" convention already used
                # for current-rate lookups in grafana/mariadb/queries.md.
                .order_by(pr.valid_from.desc())
                .first()
            )
        if row is None:
            return None
        return Rate(
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            unit_rate=row.unit_rate,
            standing_charge=row.standing_charge,
        )

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime, region: str
    ) -> list[DailyCostSummary]:
        # Joins each half-hourly consumption row to whichever agreement and
        # product_rate actually applied at that moment (not just the
        # current one), so a mid-period rate change is naturally reflected
        # day-by-day. A day with zero consumption rows produces no row here
        # at all -- it's the caller's responsibility to fill that gap, since
        # there's no consumption row to join a standing charge through.
        c = model.consumption
        a = model.agreement
        pr = model.product_rate

        with self.session_read_scope() as session:
            rows = (
                session.query(
                    c.period_from,
                    c.est_kwh.label("est_kwh"),
                    pr.unit_rate.label("unit_rate"),
                    pr.standing_charge.label("standing_charge"),
                )
                .join(
                    a,
                    and_(
                        a.energy == c.energy,
                        c.period_from >= a.valid_from,
                        or_(a.valid_to.is_(None), c.period_from < a.valid_to),
                    ),
                )
                .join(
                    pr,
                    and_(
                        pr.product_code == a.product_code,
                        pr.region == region,
                        c.period_from >= pr.valid_from,
                        or_(pr.valid_to.is_(None), c.period_from < pr.valid_to),
                    ),
                )
                .filter(
                    c.energy == as_energy_char(Energy.electricity),
                    c.period_from >= period_from,
                    c.period_from < period_to,
                )
                .all()
            )

        # Grouped in Python by Europe/London local calendar day, not the raw
        # UTC date -- Octopus's own daily reporting (and the "day" a UK user
        # means by "cost for 26 July") is local time. See ADR-0010 for why
        # this is Python/zoneinfo-based rather than SQL CONVERT_TZ.
        daily: dict[date, _DailyAccumulator] = {}
        for row in rows:
            day = local_day.to_local_date(row.period_from)
            bucket = daily.setdefault(day, _DailyAccumulator())
            bucket.total_kwh += row.est_kwh
            bucket.variable_cost += row.est_kwh * row.unit_rate
            bucket.standing_charge = max(bucket.standing_charge, row.standing_charge)
            bucket.row_count += 1

        # Octopus's consumption API has a real settlement lag -- a day can
        # still be missing rows more than 24 hours after it ends. A
        # strictly-past day must have all of that local day's expected
        # half-hourly rows (48 normally, 46/50 on a UK clock-change date) to
        # be treated as final; the current/most-recent day (period_to's
        # local date) is exempt since it's expected to be partial by
        # definition ("cost so far"). An incomplete past day drops out
        # entirely here, same as a day with zero consumption rows already
        # does, and is picked up by the caller's gap-fill.
        today = local_day.to_local_date(period_to)
        return [
            DailyCostSummary(
                date=day,
                total_kwh=bucket.total_kwh,
                day_cost_gbp=(bucket.variable_cost + bucket.standing_charge) / 100,
            )
            for day, bucket in daily.items()
            if day == today
            or bucket.row_count == local_day.expected_half_hour_count(day)
        ]

    def read_consumption_summarization_window(
        self, as_of: date
    ) -> list[ConsumptionSummary]:
        # Deliberately no lower bound on the raw `consumption` scan below:
        # gap detection (a day outside the trailing window with no existing
        # summary row) requires seeing all of history, not just the recent
        # cutoff. Table growth is bounded by the raw retention window via
        # the weekly prune_old_data job (see DataPruner), which always runs
        # after this summarization job in the same scheduling tick -- so by
        # the time pruning deletes anything, it has already been summarized.
        # `- 1` because the window is inclusive of as_of itself: 14 trailing
        # days means as_of, as_of-1, ..., as_of-13 (14 dates), not 15.
        cutoff = as_of - timedelta(days=SUMMARIZATION_WINDOW_DAYS - 1)
        with self.session_read_scope() as session:
            raw_rows = session.query(
                model.consumption.energy,
                model.consumption.period_from,
                model.consumption.est_kwh,
            ).all()

            # Grouped in Python by Europe/London local calendar day, not the
            # raw UTC date -- keeps this job's day boundaries consistent
            # with ConsumptionSummaryBackfill, which already buckets by
            # local day (it reads the still-locally-offset Octopus response
            # directly, before any DB round-trip).
            daily_totals: dict[tuple[str, date], Decimal] = {}
            for row in raw_rows:
                day = local_day.to_local_date(row.period_from)
                key = (row.energy, day)
                daily_totals[key] = daily_totals.get(key, Decimal(0)) + row.est_kwh

            # `daily_consumption_summary` is exempt from raw-data pruning
            # (kept for long-running yearly comparisons), so it grows
            # unbounded over years -- restricted to just the dates present
            # in daily_totals (bounded by raw retention) rather than
            # fetching the whole table.
            candidate_days = {day for _, day in daily_totals}
            existing_summary_days: set[tuple[str, date]] = set()
            if candidate_days:
                existing_summary_days = {
                    (row.energy, row.date)
                    for row in session.query(
                        model.daily_consumption_summary.energy,
                        model.daily_consumption_summary.date,
                    )
                    .filter(model.daily_consumption_summary.date.in_(candidate_days))
                    .all()
                }

        return [
            ConsumptionSummary(
                energy=energy_from_char(energy_char),
                date=day,
                total_kwh=total_kwh,
            )
            for (energy_char, day), total_kwh in daily_totals.items()
            if day >= cutoff or (energy_char, day) not in existing_summary_days
        ]

    def write_consumption_summary(self, summaries: list[ConsumptionSummary]) -> None:
        records = [
            model.daily_consumption_summary(
                energy=as_energy_char(summary.energy),
                date=summary.date,
                total_kwh=summary.total_kwh,
            )
            for summary in summaries
        ]
        self._write_all(records, "Consumption summary data")

    def has_successful_job_run(self, job_name: str) -> bool:
        with self.session_read_scope() as session:
            return (
                session.query(model.job_run)
                .filter_by(job_name=job_name, status="success")
                .first()
                is not None
            )

    def latest_job_run_is_successful(self, job_name: str) -> bool:
        with self.session_read_scope() as session:
            latest = (
                session.query(model.job_run)
                .filter_by(job_name=job_name)
                .order_by(model.job_run.ran_at.desc(), model.job_run.id.desc())
                .first()
            )
            return latest is not None and latest.status == "success"

    def record_job_run(
        self, job_name: str, status: str, error: str | None = None
    ) -> None:
        try:
            with self.session_write_scope() as s:
                record = model.job_run(
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

    def prune_consumption_older_than(self, cutoff: datetime) -> int:
        try:
            with self.session_write_scope() as session:
                deleted = (
                    session.query(model.consumption)
                    .filter(model.consumption.period_from < cutoff)
                    .delete(synchronize_session=False)
                )
                logger.debug(
                    f"Pruned {deleted} consumption row(s) older than {cutoff}."
                )
                return deleted
        except Exception as e:
            logger.error(f"Failed to prune consumption data: {e}")
            raise MariaDBError(e) from e

    def prune_product_rates_older_than(self, cutoff: datetime) -> int:
        try:
            with self.session_write_scope() as session:
                deleted = (
                    session.query(model.product_rate)
                    .filter(
                        model.product_rate.valid_to.isnot(None),
                        model.product_rate.valid_to < cutoff,
                    )
                    .delete(synchronize_session=False)
                )
                logger.debug(
                    f"Pruned {deleted} product_rate row(s) older than {cutoff}."
                )
                return deleted
        except Exception as e:
            logger.error(f"Failed to prune product rate data: {e}")
            raise MariaDBError(e) from e

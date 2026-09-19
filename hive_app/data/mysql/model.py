from typing import ClassVar

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, String
from sqlalchemy.ext.declarative import declarative_base

SQLBase = declarative_base()


class heating_status(SQLBase):
    __tablename__ = "heating_status"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "octopus"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    polled_at = Column(DateTime, nullable=False)
    current_temp = Column(Float)
    target_temp = Column(Float)
    mode = Column(String(20))
    state = Column(String(20))
    boost_active = Column(Boolean)
    boost_ends_at = Column(DateTime)
    schedule = Column(JSON)


class hive_auth_state(SQLBase):
    __tablename__ = "hive_auth_state"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "octopus"}

    # Single-row table (see ADR context in hive_app/data/mysql/client.py's
    # HIVE_AUTH_STATE_ID): the id is always the same fixed value, so every
    # write upserts the same row rather than accumulating history.
    #
    # All columns below are safely nullable=False despite ADR-0005's
    # additive-only Schema Sync caveat (see cost_forecast.energy in
    # app/data/mysql/model.py for the case where that caveat DOES apply):
    # this table is brand new, introduced in this same PR, never deployed
    # to production before -- create_all() creates it with every column
    # already present on first real deploy, so _sync_missing_columns'
    # ALTER-TABLE-on-an-existing-table path is never exercised for it. If a
    # future column is ever added to this already-live table, that new
    # column would need the same nullable/backfill treatment cost_forecast
    # used.
    id = Column(Integer, primary_key=True)
    refresh_token = Column(String(2000), nullable=False)
    device_group_key = Column(String(200), nullable=False)
    device_key = Column(String(200), nullable=False)
    device_password = Column(String(200), nullable=False)
    updated_at = Column(DateTime, nullable=False)


class job_run(SQLBase):
    # Same table (octopus.job_run) as app/data/mysql/model.py's job_run --
    # deliberately shared per the spec's shared-MariaDB-instance assumption
    # (Wayfinder issue #492, still unresolved). Each app's Schema Sync only
    # knows about its own SQLBase metadata, so a column added to one app's
    # model here would NOT be added by the other app's schema sync -- keep
    # both definitions identical, or add a column to both, if this ever
    # changes.
    __tablename__ = "job_run"
    __table_args__: ClassVar[tuple[Index, dict[str, str]]] = (
        Index("ix_job_run_job_name_ran_at", "job_name", "ran_at"),
        {"schema": "octopus"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)
    ran_at = Column(DateTime, nullable=False)
    error_message = Column(String(1000))

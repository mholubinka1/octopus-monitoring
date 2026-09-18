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
    id = Column(Integer, primary_key=True)
    refresh_token = Column(String(2000), nullable=False)
    device_group_key = Column(String(200), nullable=False)
    device_key = Column(String(200), nullable=False)
    updated_at = Column(DateTime, nullable=False)


class job_run(SQLBase):
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

from typing import ClassVar

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String

from libs.common.common.mariadb.model import SQLBase, job_run

__all__ = ["SQLBase", "job_run"]


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

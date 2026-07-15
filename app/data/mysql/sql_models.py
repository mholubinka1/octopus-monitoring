from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.ext.declarative import declarative_base

SQLBase = declarative_base()


class consumption(SQLBase):
    __tablename__ = "consumption"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    energy = Column(String)
    period_from = Column(DateTime)
    period_to = Column(DateTime)
    raw_value = Column(Float)
    unit = Column(String)
    est_kwh = Column(Float)


class tariff(SQLBase):
    __tablename__ = "tariff"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    consumption_id = Column(String)


class cost(SQLBase):
    __tablename__ = "cost"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    consumption_id = Column(String)


class job_run(SQLBase):
    __tablename__ = "job_run"
    __table_args__ = {"schema": "octopus"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)
    ran_at = Column(DateTime, nullable=False)
    error_message = Column(String(1000))

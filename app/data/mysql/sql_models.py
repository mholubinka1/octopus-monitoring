from sqlalchemy import Column, DateTime, Float, String
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

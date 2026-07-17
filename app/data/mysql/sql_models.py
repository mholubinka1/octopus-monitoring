from sqlalchemy import Column, DateTime, Float, Integer, Numeric, String
from sqlalchemy.ext.declarative import declarative_base

SQLBase = declarative_base()


class consumption(SQLBase):
    __tablename__ = "consumption"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    energy = Column(String)
    period_from = Column(DateTime, nullable=False)
    period_to = Column(DateTime, nullable=False)
    raw_value = Column(Float, nullable=False)
    unit = Column(String)
    est_kwh = Column(Float, nullable=False)


class agreement(SQLBase):
    __tablename__ = "agreement"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    energy = Column(String)
    product_code = Column(String)
    tariff_code = Column(String)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime)


class product(SQLBase):
    __tablename__ = "product"
    __table_args__ = {"schema": "octopus"}

    product_code = Column(String, primary_key=True)
    display_name = Column(String)
    direction = Column(String)


class product_rate(SQLBase):
    __tablename__ = "product_rate"
    __table_args__ = {"schema": "octopus"}

    id = Column(String, primary_key=True)
    product_code = Column(String, nullable=False)
    region = Column(String)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime)
    unit_rate = Column(Numeric(9, 6), nullable=False)
    standing_charge = Column(Numeric(9, 6), nullable=False)


class job_run(SQLBase):
    __tablename__ = "job_run"
    __table_args__ = {"schema": "octopus"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)
    ran_at = Column(DateTime, nullable=False)
    error_message = Column(String(1000))

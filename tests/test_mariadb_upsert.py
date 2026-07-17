import pytest
from data.mysql.client import upsert
from sqlalchemy import Column, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_TestBase = declarative_base()


class _RequiredFieldRecord(_TestBase):
    __tablename__ = "required_field_record"

    id = Column(String, primary_key=True)
    required_field = Column(String, nullable=False)


@pytest.fixture(name="upsert_session")
def _upsert_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _TestBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_upsert_raises_when_a_non_primary_key_constraint_is_violated(
    upsert_session: Session,
) -> None:
    record = _RequiredFieldRecord(id="1", required_field=None)  # type: ignore[misc]

    with pytest.raises(RuntimeError):
        upsert(upsert_session, record)

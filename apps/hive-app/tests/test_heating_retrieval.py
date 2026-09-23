from datetime import UTC, datetime

import pytest
from hive_app.data.heating import HeatingRetriever
from hive_app.data.model import HeatingStatus, HiveAuthState
from hive_app.data.mysql import model
from hive_app.data.mysql.client import MariaDBClient


class _FakeHiveSource:
    """A fake HiveSource for tests: a fixed HeatingStatus and a real
    MariaDBClient underneath, mirroring test_pricing_retrieval.py's
    _RealPricingSource seam shape for PricingRetriever. Auth verbs are
    unused by HeatingRetriever -- stubbed only to satisfy the HiveSource
    Protocol's full shape, same spirit as _FakeAuthHiveSource's unused
    heating verbs in test_hive_authentication.py."""

    def __init__(self, mariadb: MariaDBClient, status: HeatingStatus) -> None:
        self._mariadb = mariadb
        self._status = status

    def fetch_heating_status(self) -> HeatingStatus:
        return self._status

    def persist_heating_status(self, status: HeatingStatus) -> None:
        self._mariadb.write_heating_status(status)

    def read_auth_state(self) -> HiveAuthState | None:
        raise NotImplementedError

    def login(self) -> HiveAuthState:
        raise NotImplementedError

    def resume(self, state: HiveAuthState) -> HiveAuthState:
        raise NotImplementedError

    def persist_auth_state(self, state: HiveAuthState) -> None:
        raise NotImplementedError


def _make_status() -> HeatingStatus:
    return HeatingStatus(
        polled_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        current_temp=19.5,
        target_temp=21.0,
        mode="SCHEDULE",
        state="ON",
        boost_active=False,
        boost_ends_at=None,
        schedule={"now": "21.0", "next": "18.0", "later": "19.0"},
    )


def test_refresh_persists_the_polled_heating_status(
    mariadb_client: MariaDBClient,
) -> None:
    status = _make_status()
    source = _FakeHiveSource(mariadb_client, status)

    HeatingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.heating_status).all()

    assert len(stored) == 1
    assert stored[0].current_temp == status.current_temp
    assert stored[0].target_temp == status.target_temp
    assert stored[0].mode == status.mode
    assert stored[0].state == status.state
    assert stored[0].boost_active == status.boost_active
    assert stored[0].schedule == status.schedule


class _FailingHiveSource:
    """A fake HiveSource whose poll raises an ordinary transient error --
    proves HeatingRetriever.refresh() does no retry/backoff/swallowing of
    its own (that's the generic job-wrapper's job); it just propagates."""

    def fetch_heating_status(self) -> HeatingStatus:
        raise ConnectionError("Hive backend unreachable")

    def persist_heating_status(self, status: HeatingStatus) -> None:
        raise AssertionError("persist_heating_status should never be reached")

    def read_auth_state(self) -> HiveAuthState | None:
        raise NotImplementedError

    def login(self) -> HiveAuthState:
        raise NotImplementedError

    def resume(self, state: HiveAuthState) -> HiveAuthState:
        raise NotImplementedError

    def persist_auth_state(self, state: HiveAuthState) -> None:
        raise NotImplementedError


def test_refresh_propagates_a_transient_poll_failure_without_swallowing_it() -> None:
    source = _FailingHiveSource()

    with pytest.raises(ConnectionError, match="Hive backend unreachable"):
        HeatingRetriever(source).refresh()

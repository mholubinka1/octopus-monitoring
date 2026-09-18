from datetime import UTC, datetime

from hive_app.data.auth import HiveAuthenticator
from hive_app.data.model import HeatingStatus, HiveAuthState
from hive_app.data.mysql.client import MariaDBClient


class _FakeAuthHiveSource:
    """A fake HiveSource for auth-branching tests: a real MariaDBClient
    backs read_auth_state/persist_auth_state (so persistence is genuinely
    exercised), while login()/resume() are recorded rather than performing
    any real Cognito SRP work -- same spirit as _FakeHiveSource in
    test_heating_retrieval.py."""

    def __init__(self, mariadb: MariaDBClient) -> None:
        self._mariadb = mariadb
        self.login_called = False
        self.resume_called_with: HiveAuthState | None = None

    def fetch_heating_status(self) -> HeatingStatus:
        raise NotImplementedError

    def persist_heating_status(self, status: HeatingStatus) -> None:
        raise NotImplementedError

    def read_auth_state(self) -> HiveAuthState | None:
        return self._mariadb.read_hive_auth_state()

    def login(self) -> HiveAuthState:
        self.login_called = True
        return HiveAuthState(
            refresh_token="fresh-refresh-token",
            device_group_key="fresh-device-group-key",
            device_key="fresh-device-key",
            updated_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        )

    def resume(self, state: HiveAuthState) -> HiveAuthState:
        self.resume_called_with = state
        return state

    def persist_auth_state(self, state: HiveAuthState) -> None:
        self._mariadb.write_hive_auth_state(state)


def test_no_existing_auth_state_takes_the_interactive_login_path(
    mariadb_client: MariaDBClient,
) -> None:
    source = _FakeAuthHiveSource(mariadb_client)

    HiveAuthenticator(source).authenticate()

    assert source.login_called is True
    assert source.resume_called_with is None

    stored = mariadb_client.read_hive_auth_state()
    assert stored is not None
    assert stored.refresh_token == "fresh-refresh-token"
    assert stored.device_group_key == "fresh-device-group-key"
    assert stored.device_key == "fresh-device-key"


def test_existing_auth_state_takes_only_the_resume_path(
    mariadb_client: MariaDBClient,
) -> None:
    existing_state = HiveAuthState(
        refresh_token="existing-refresh-token",
        device_group_key="existing-device-group-key",
        device_key="existing-device-key",
        updated_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
    )
    mariadb_client.write_hive_auth_state(existing_state)
    source = _FakeAuthHiveSource(mariadb_client)

    HiveAuthenticator(source).authenticate()

    assert source.login_called is False
    assert source.resume_called_with == existing_state

    stored = mariadb_client.read_hive_auth_state()
    assert stored == existing_state

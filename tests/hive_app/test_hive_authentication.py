from datetime import UTC, datetime

from hive_app.data.auth import HiveAuthenticator
from hive_app.data.model import HeatingStatus, HiveAuthState


class _FakeAuthHiveSource:
    """A fake HiveSource for auth-branching tests: read_auth_state/
    persist_auth_state are backed by a plain in-memory instance attribute
    (mirroring HiveApiSource's real file-based storage, without touching a
    real file), while login()/resume() are recorded rather than performing
    any real Cognito SRP work -- same spirit as _FakeHiveSource in
    test_heating_retrieval.py."""

    def __init__(self, initial_state: HiveAuthState | None = None) -> None:
        self._state = initial_state
        self.login_called = False
        self.resume_called_with: HiveAuthState | None = None

    def fetch_heating_status(self) -> HeatingStatus:
        raise NotImplementedError

    def persist_heating_status(self, status: HeatingStatus) -> None:
        raise NotImplementedError

    def read_auth_state(self) -> HiveAuthState | None:
        return self._state

    def login(self) -> HiveAuthState:
        self.login_called = True
        return HiveAuthState(
            refresh_token="fresh-refresh-token",
            device_group_key="fresh-device-group-key",
            device_key="fresh-device-key",
            device_password="fresh-device-password",
            updated_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        )

    def resume(self, state: HiveAuthState) -> HiveAuthState:
        self.resume_called_with = state
        return state

    def persist_auth_state(self, state: HiveAuthState) -> None:
        self._state = state


def test_no_existing_auth_state_takes_the_interactive_login_path() -> None:
    source = _FakeAuthHiveSource()

    HiveAuthenticator(source).authenticate()

    assert source.login_called is True
    assert source.resume_called_with is None

    stored = source.read_auth_state()
    assert stored is not None
    assert stored.refresh_token == "fresh-refresh-token"
    assert stored.device_group_key == "fresh-device-group-key"
    assert stored.device_key == "fresh-device-key"


def test_existing_auth_state_takes_only_the_resume_path() -> None:
    existing_state = HiveAuthState(
        refresh_token="existing-refresh-token",
        device_group_key="existing-device-group-key",
        device_key="existing-device-key",
        device_password="existing-device-password",
        updated_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
    )
    source = _FakeAuthHiveSource(initial_state=existing_state)

    HiveAuthenticator(source).authenticate()

    assert source.login_called is False
    assert source.resume_called_with == existing_state

    stored = source.read_auth_state()
    assert stored == existing_state

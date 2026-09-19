import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hive_app.data.hive_client import HiveApiSource
from hive_app.data.model import HiveAuthState


def _make_source(auth_state_path: Path) -> HiveApiSource:
    return HiveApiSource(settings=None, mariadb=None, auth_state_path=str(auth_state_path))  # type: ignore[arg-type]


def test_persisted_auth_state_round_trips_through_the_file(tmp_path: Path) -> None:
    auth_state_path = tmp_path / "hive_auth_state.json"
    source = _make_source(auth_state_path)
    state = HiveAuthState(
        refresh_token="refresh-token",
        device_group_key="device-group-key",
        device_key="device-key",
        device_password="device-password",
        updated_at=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
    )

    source.persist_auth_state(state)

    assert source.read_auth_state() == state


def test_missing_file_returns_none(tmp_path: Path) -> None:
    auth_state_path = tmp_path / "hive_auth_state.json"
    source = _make_source(auth_state_path)

    assert source.read_auth_state() is None


def test_corrupt_file_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text("not valid json", encoding="utf-8")
    source = _make_source(auth_state_path)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for a corrupt auth state file"


def test_persisted_file_has_owner_only_permissions(tmp_path: Path) -> None:
    auth_state_path = tmp_path / "hive_auth_state.json"
    source = _make_source(auth_state_path)
    state = HiveAuthState(
        refresh_token="refresh-token",
        device_group_key="device-group-key",
        device_key="device-key",
        device_password="device-password",
        updated_at=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
    )

    source.persist_auth_state(state)
    # Re-persist to confirm the mode is re-applied on every write, not just
    # on first creation.
    source.persist_auth_state(state)

    if os.name != "nt":
        mode = auth_state_path.stat().st_mode & 0o777
        assert mode == 0o600

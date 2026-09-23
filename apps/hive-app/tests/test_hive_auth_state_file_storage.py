import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hive_app.common.config import HiveSettings
from hive_app.data.hive_client import HiveApiSource
from hive_app.data.model import HiveAuthState


def _make_source(auth_state_path: Path) -> HiveApiSource:
    settings = HiveSettings(
        username="someone@example.com",
        password="hunter2",
        auth_state_path=str(auth_state_path),
    )
    return HiveApiSource(settings=settings, mariadb=None)  # type: ignore[arg-type]


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


def test_file_missing_a_required_key_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A file from an older/partial schema (missing a field this version
    expects) must degrade to the same fallback as a missing file, not raise
    an uncaught KeyError."""
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text(
        json.dumps({"refresh_token": "refresh-token"}), encoding="utf-8"
    )
    source = _make_source(auth_state_path)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for a file missing a required key"


def test_file_with_an_unparsable_timestamp_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """updated_at that isn't a valid ISO-8601 string must degrade to the
    same fallback as a missing file, not raise an uncaught ValueError."""
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-token",
                "device_group_key": "device-group-key",
                "device_key": "device-key",
                "device_password": "device-password",
                "updated_at": "not-a-timestamp",
            }
        ),
        encoding="utf-8",
    )
    source = _make_source(auth_state_path)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for an unparsable timestamp"


def test_field_with_the_wrong_json_type_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A field present with the right key but the wrong JSON type (e.g. a
    list instead of a token string) must degrade to the same fallback as a
    missing file, not silently construct a HiveAuthState that later fails
    Cognito's SRP flow unpredictably."""
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text(
        json.dumps(
            {
                "refresh_token": [],
                "device_group_key": "device-group-key",
                "device_key": "device-key",
                "device_password": "device-password",
                "updated_at": "2026-09-19T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    source = _make_source(auth_state_path)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for a field with the wrong JSON type"


def test_file_containing_valid_json_that_is_not_an_object_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid JSON that isn't an object (e.g. a bare list or null) must
    degrade to the same fallback as a missing file, not raise an uncaught
    TypeError from indexing into it."""
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text(json.dumps([]), encoding="utf-8")
    source = _make_source(auth_state_path)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for JSON that isn't an object"


def test_unreadable_file_returns_none_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that exists but can't be read (e.g. a permissions problem on
    the 0o600-restricted file this class itself writes) must degrade to the
    same "no prior successful login" fallback as a missing or corrupt file,
    not propagate an uncaught OSError and crash startup."""
    auth_state_path = tmp_path / "hive_auth_state.json"
    auth_state_path.write_text("{}", encoding="utf-8")
    source = _make_source(auth_state_path)

    def _raise_permission_error(*args: object, **kwargs: object) -> str:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_permission_error)

    with caplog.at_level("WARNING"):
        result = source.read_auth_state()

    assert result is None
    assert any(
        record.levelname == "WARNING" for record in caplog.records
    ), "expected a warning to be logged for an unreadable auth state file"


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

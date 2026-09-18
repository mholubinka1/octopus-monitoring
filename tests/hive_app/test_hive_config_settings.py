from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from hive_app.common.config import HiveApplicationSettings, get_settings

VALID_CONFIG: dict[str, Any] = {
    "hive": {"username": "someone@example.com", "password": "hunter2"},
    "mariadb": {
        "host": "localhost",
        "port": 3306,
        "database": "octopus",
        "username": "test",
        "password": "test",
    },
    "weather_underground": {"api_key": "wu-test-key", "station_id": "IBECKE4"},
    "ntfy": {"topic_url": "https://ntfy.sh/hive-app-reauth"},
    "location": {"latitude": 51.5, "longitude": -0.1},
}


def test_valid_config_yaml_produces_correctly_typed_settings() -> None:
    settings = HiveApplicationSettings.model_validate(VALID_CONFIG)

    assert settings.hive.username == "someone@example.com"
    assert settings.hive.password == "hunter2"
    assert settings.mariadb.host == "localhost"
    assert settings.mariadb.port == 3306
    assert settings.mariadb.database == "octopus"
    assert settings.weather_underground.api_key == "wu-test-key"
    assert settings.weather_underground.station_id == "IBECKE4"
    assert settings.ntfy.topic_url == "https://ntfy.sh/hive-app-reauth"
    assert settings.location.latitude == 51.5
    assert settings.location.longitude == -0.1


def test_missing_required_config_field_raises_a_validation_error_naming_the_field() -> (
    None
):
    invalid_config = {
        "hive": {"username": "someone@example.com"},
        "mariadb": VALID_CONFIG["mariadb"],
        "weather_underground": VALID_CONFIG["weather_underground"],
        "ntfy": VALID_CONFIG["ntfy"],
        "location": VALID_CONFIG["location"],
    }

    with pytest.raises(ValidationError, match="password"):
        HiveApplicationSettings.model_validate(invalid_config)


def test_malformed_config_field_value_is_not_leaked_to_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaked_marker = "hunter2-do-not-log-me"
    hive_config = dict(VALID_CONFIG["hive"])
    hive_config["password"] = [leaked_marker]
    invalid_config = {
        "hive": hive_config,
        "mariadb": VALID_CONFIG["mariadb"],
        "weather_underground": VALID_CONFIG["weather_underground"],
        "ntfy": VALID_CONFIG["ntfy"],
        "location": VALID_CONFIG["location"],
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(invalid_config))

    logged_messages: list[str] = []
    monkeypatch.setattr(
        "hive_app.common.config.logger.critical", logged_messages.append
    )

    with pytest.raises(SystemExit):
        get_settings(str(config_file))

    logged_text = " ".join(logged_messages)
    assert leaked_marker not in logged_text
    assert "password" in logged_text

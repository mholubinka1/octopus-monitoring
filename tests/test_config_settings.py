from pathlib import Path
from typing import Any, Dict

import pytest
import yaml
from common.config import ApplicationSettings, get_settings
from pydantic import ValidationError

VALID_CONFIG: Dict[str, Any] = {
    "octopus": {"account_number": "A-1234ABCD", "api_key": "sk_live_test"},
    "mariadb": {
        "host": "localhost",
        "port": 3306,
        "database": "octopus",
        "username": "test",
        "password": "test",
    },
    "data_refresh": {
        "polling_interval_seconds": 5,
        "refresh_interval_hours": 4,
        "historical_limit_days": 45,
    },
}


def test_valid_config_yaml_produces_correctly_typed_settings() -> None:
    settings = ApplicationSettings.model_validate(VALID_CONFIG)

    assert settings.octopus.account_number == "A-1234ABCD"
    assert settings.octopus.api_key == "sk_live_test"
    assert settings.mariadb.host == "localhost"
    assert settings.mariadb.port == 3306
    assert settings.mariadb.database == "octopus"
    assert settings.refresh_settings.polling_interval == 5
    assert settings.refresh_settings.refresh_interval == 4
    assert settings.refresh_settings.historical_limit == 45


def test_missing_required_config_field_raises_a_validation_error_naming_the_field() -> (
    None
):
    invalid_config = {
        "octopus": {"account_number": "A-1234ABCD"},
        "mariadb": VALID_CONFIG["mariadb"],
        "data_refresh": VALID_CONFIG["data_refresh"],
    }

    with pytest.raises(ValidationError, match="api_key"):
        ApplicationSettings.model_validate(invalid_config)


def test_malformed_config_field_value_is_not_leaked_to_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaked_marker = "hunter2-do-not-log-me"
    mariadb_config = dict(VALID_CONFIG["mariadb"])
    mariadb_config["password"] = [leaked_marker]
    invalid_config = {
        "octopus": VALID_CONFIG["octopus"],
        "mariadb": mariadb_config,
        "data_refresh": VALID_CONFIG["data_refresh"],
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(invalid_config))

    logged_messages: list[str] = []
    monkeypatch.setattr("common.config.logger.critical", logged_messages.append)

    with pytest.raises(SystemExit):
        get_settings(str(config_file))

    logged_text = " ".join(logged_messages)
    assert leaked_marker not in logged_text
    assert "password" in logged_text

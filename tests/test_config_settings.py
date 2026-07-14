import pytest
from common.config import ApplicationSettings
from pydantic import ValidationError

VALID_CONFIG = {
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

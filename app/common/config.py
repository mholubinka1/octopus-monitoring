import logging.config
import sys
from logging import Logger, getLogger

import yaml
from common.logging import APP_LOGGER_NAME, config
from pydantic import BaseModel, ConfigDict, Field

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class OctopusAPISettings(BaseModel):
    account_number: str
    api_key: str


class MariaDBSettings(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password: str


class RefreshSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    polling_interval: int = Field(alias="polling_interval_seconds")
    refresh_interval: int = Field(alias="refresh_interval_hours")
    historical_limit: int = Field(alias="historical_limit_days")


class ApplicationSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    octopus: OctopusAPISettings
    mariadb: MariaDBSettings
    refresh_settings: RefreshSettings = Field(alias="data_refresh")


def get_settings(
    config_file_path: str,
) -> ApplicationSettings:
    try:
        with open(config_file_path, "r") as file:
            yaml_settings = yaml.safe_load(file)
        settings = ApplicationSettings.model_validate(yaml_settings)
        logger.info(f"Successfully loaded settings from {config_file_path}")
        return settings
    except Exception as e:
        logger.critical(
            f"Failed to load application settings from {config_file_path}: {e}"
        )
        sys.exit(1)

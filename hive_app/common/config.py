import logging.config
import sys
from logging import Logger, getLogger

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from hive_app.common.logging import APP_LOGGER_NAME, config

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class HiveSettings(BaseModel):
    username: str
    password: str


class MariaDBSettings(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password: str


class WeatherUndergroundSettings(BaseModel):
    api_key: str
    station_id: str


class NtfySettings(BaseModel):
    topic_url: str


class LocationSettings(BaseModel):
    latitude: float
    longitude: float


class HiveApplicationSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hive: HiveSettings
    mariadb: MariaDBSettings
    weather_underground: WeatherUndergroundSettings
    ntfy: NtfySettings
    location: LocationSettings


def get_settings(
    config_file_path: str,
) -> HiveApplicationSettings:
    try:
        with open(config_file_path, "r", encoding="utf-8") as file:
            yaml_settings = yaml.safe_load(file)
        settings = HiveApplicationSettings.model_validate(yaml_settings)
        logger.info(f"Successfully loaded settings from {config_file_path}")
        return settings
    except ValidationError as e:
        invalid_fields = ", ".join(
            ".".join(str(part) for part in error["loc"]) for error in e.errors()
        )
        logger.critical(
            f"Failed to load application settings from {config_file_path}: "
            f"invalid or missing field(s): {invalid_fields}"
        )
        sys.exit(1)
    except Exception as e:
        logger.critical(
            f"Failed to load application settings from {config_file_path}: {e}"
        )
        sys.exit(1)

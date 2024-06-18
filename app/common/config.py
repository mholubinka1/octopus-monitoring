import logging.config
import sys
from logging import Logger, getLogger
from typing import Dict

import yaml
from common.logging import APP_LOGGER_NAME, config

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class OctopusAPISettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.account_number = yaml_settings["octopus"]["account_number"]
        self.api_key = yaml_settings["octopus"]["api_key"]


class InfluxV2Settings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.url = yaml_settings["influxv2"]["url"]
        self.organization = yaml_settings["influxv2"]["organization"]
        self.bucket = yaml_settings["influxv2"]["bucket"]
        self.token = yaml_settings["influxv2"]["all-access-token"]


class MariaDBSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.host = yaml_settings["maria-db"]["host"]
        self.port = yaml_settings["maria-db"]["port"]
        self.database = yaml_settings["maria-db"]["database"]
        self.username = yaml_settings["maria-db"]["username"]
        self.password = yaml_settings["maria-db"]["password"]


class RefreshSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.polling_interval = yaml_settings["data_refresh"][
            "polling_interval_seconds"
        ]
        self.update_interval = yaml_settings["data_refresh"]["update_interval_seconds"]
        self.historical_limit = yaml_settings["data_refresh"]["historical_limit_days"]


class ApplicationSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.octopus = OctopusAPISettings(yaml_settings)
        self.influxdb = InfluxV2Settings(yaml_settings)
        self.mariadb = MariaDBSettings(yaml_settings)
        self.refresh_settings = RefreshSettings(yaml_settings)


def get_settings(
    config_file_path: str,
) -> ApplicationSettings:
    try:
        with open(config_file_path, "r") as file:
            settings = yaml.safe_load(file)
        logger.info(f"Successfully loaded settings from {config_file_path}")
        return ApplicationSettings(settings)
    except Exception as e:
        logger.critical(
            f"Failed to load application settings from {config_file_path}: {e}"
        )
        sys.exit(1)

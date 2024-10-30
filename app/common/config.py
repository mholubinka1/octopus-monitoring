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


class MariaDBSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.host = yaml_settings["mariadb"]["host"]
        self.port = yaml_settings["mariadb"]["port"]
        self.database = yaml_settings["mariadb"]["database"]
        self.username = yaml_settings["mariadb"]["username"]
        self.password = yaml_settings["mariadb"]["password"]


class RefreshSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.polling_interval = yaml_settings["data_refresh"][
            "polling_interval_seconds"
        ]
        self.refresh_interval = yaml_settings["data_refresh"]["refresh_interval_hours"]
        self.historical_limit = yaml_settings["data_refresh"]["historical_limit_days"]


class ApplicationSettings:
    def __init__(self, yaml_settings: Dict) -> None:
        self.octopus = OctopusAPISettings(yaml_settings)
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

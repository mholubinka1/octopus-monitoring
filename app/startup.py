import logging.config
from argparse import Namespace
from logging import Logger, getLogger
from typing import Any, Optional

import yaml
from common.constants import APP_LOGGER_NAME
from common.exceptions import ConfigurationFileError
from common.logging import config
from data.api import EnergyMeter

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def get_api_settings(
    args: Namespace,
) -> Any:
    try:
        config_file_path = args.config_file
        with open(config_file_path, "r") as file:
            settings = yaml.safe_load(file)
        logger.info(
            f"Successfully loaded settings from configuration file: {config_file_path}"
        )
        return settings
    except Exception as e:
        logger.critical(e)
        return None, None, None


def parse_api_settings(
    settings: Any,
) -> tuple[Optional[str], Optional[EnergyMeter], Optional[EnergyMeter]]:
    try:
        api_key = settings["api"]["key"]
    except Exception:
        raise ConfigurationFileError("Failed to read API key from configuration.")

    try:
        electricity = EnergyMeter(
            sn=settings["electricity"]["sn"],
            mpan=settings["electricity"]["mpan"],
            mprn=None,
        )
    except Exception:
        raise ConfigurationFileError(
            "Configuration Error: Failed to read Electricity Meter properties."
        )

    try:
        gas = EnergyMeter(
            sn=settings["gas"]["sn"], mpan=None, mprn=settings["gas"]["mprn"]
        )
    except Exception:
        raise ConfigurationFileError(
            "Configuration Error: failed to read Gas Meter properties."
        )
    logger.info(
        f"Successfully parsed API and energy meter settings:\nAPI Key: {api_key}\nElectricity Meter: [MPAN: {electricity.mpan}, SN: {electricity.sn}]\nGas Meter: [MPRN: {gas.mprn}, SN: {gas.sn}]"
    )
    return api_key, electricity, gas

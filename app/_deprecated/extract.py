"""
import logging.config
from datetime import datetime, timedelta
from logging import Logger, getLogger
from typing import List

from common.logging import APP_LOGGER_NAME, config
from data.influx import InfluxDB
from data.octopus.api import Consumption, OctopusEnergyAPIClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def write_new_consumption_history(
    period_from: datetime, api: OctopusEnergyAPIClient, influxdb: InfluxDB
) -> datetime:
    logger.info("Retrieving full consumption history.")

    new_period_from, new_consumption = extract_new_consumption(api, period_from)
    yesterday = extract_yesterday_consumption(api)
    month_to_date = extract_month_to_date_consumption(api)

    if len(new_consumption) != 0:
        influxdb.save_consumption(new_consumption, yesterday, month_to_date)
        logger.info("New consumption retrieved and saved.")
    else:
        logger.info("No new consumption data available.")

    return new_period_from


def write_full_consumption_history(api: OctopusEnergyAPIClient, influxdb: InfluxDB) -> datetime:
    logger.info("Retrieving full consumption history.")

    latest_period_to, consumption_history = extract_consumption_history(api)
    yesterday = extract_yesterday_consumption(api)
    month_to_date = extract_month_to_date_consumption(api)

    if len(consumption_history) != 0:
        influxdb.save_consumption(consumption_history, yesterday, month_to_date)
        logger.info("Historical consumption retrieved and saved.")
    else:
        logger.info("No historical consumption data available.")

    return latest_period_to


# region Data Extraction Methods


def extract_consumption_history(
    api: OctopusAPI, period_from: datetime = datetime.fromisoformat("1970-01-01T00:00Z")
) -> tuple[datetime, List[Consumption]]:
    consumption_history = api.get_consumption()
    if len(consumption_history) == 0:
        return period_from, consumption_history
    latest_period_to = consumption_history[-1].end
    return latest_period_to, consumption_history


def extract_new_consumption(
    api: OctopusAPI, period_from: datetime
) -> tuple[datetime, List[Consumption]]:
    new_consumption = api.get_consumption(period_from=period_from)
    if len(new_consumption) == 0:
        return period_from, new_consumption
    latest_period_to = new_consumption[-1].end
    return latest_period_to, new_consumption


def extract_yesterday_consumption(api: OctopusAPI) -> List[Consumption]:
    yesterday = datetime.utcnow() - timedelta(days=1)
    yesterday = datetime(yesterday.year, yesterday.month, yesterday.day)
    end_of_day = yesterday + timedelta(days=1)
    return api.get_cumulative_consumption(yesterday, end_of_day)


def extract_month_to_date_consumption(api: OctopusAPI) -> List[Consumption]:
    now = datetime.utcnow()
    first_day_of_month = datetime(now.year, now.month, 1)
    return api.get_cumulative_consumption(first_day_of_month, now)


# endregion
"""

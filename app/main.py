import argparse
import logging.config
from asyncio import sleep
from datetime import datetime
from logging import Logger, getLogger

from common.constants import APP_LOGGER_NAME
from common.logging import config
from data.api import OctopusAPI
from data.extract import write_full_consumption_history, write_new_consumption_history
from data.influx import InfluxDB
from startup import get_api_settings, parse_api_settings

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

logging.info("Starting octopus-monitoring...")

parser = argparse.ArgumentParser()
parser.add_argument("--config-file")
args = parser.parse_args()

settings = get_api_settings(args)
(api_key, electricity, gas) = parse_api_settings(settings)

api = OctopusAPI(api_key, electricity, gas)
influxdb = InfluxDB(settings)

logging.info("Startup complete.")

logging.info("Retrieving full consumption history.")

latest_period_to: datetime = write_full_consumption_history(api, influxdb)

logging.info("Historical consumption retrieved and saved.")

last_retrieved_hour = datetime.utcnow().hour

polling_interval_seconds = 60
logging.info("Starting periodic retrieval service...")
logging.info(
    f"Consumption data update interval ~ 1 hour and polling interval: {polling_interval_seconds}"
)

period_from: datetime = latest_period_to
while not sleep(60):
    current_hour = datetime.utcnow().hour
    if not last_retrieved_hour == current_hour:
        logging.info(
            "Update interval threshold reached, retrieving any new consumption data..."
        )
        new_period_from = write_new_consumption_history(period_from, api, influxdb)

    logging.debug("Update interval threshold not reached, waiting to poll again.")

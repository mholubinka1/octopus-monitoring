import argparse
import logging.config
import time
from datetime import datetime
from logging import Logger, getLogger
from typing import Any, Callable, Optional

from common.constants import APP_LOGGER_NAME
from common.logging import config
from data.api import OctopusAPI
from data.extract import write_full_consumption_history
from data.influx import InfluxDB
from data.poll import ConsumptionPoller
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

polling_interval_seconds = 60
logging.info("Starting periodic retrieval service...")
logging.info(
    f"Consumption data update interval ~ 1 hour and polling interval: {polling_interval_seconds}"
)

last_retrieved_hour = datetime.utcnow().hour
poller = ConsumptionPoller(api, influxdb, latest_period_to, last_retrieved_hour)


def every(delay: int, poll: Callable[..., Optional[Any]]) -> None:
    next_time = time.time() + polling_interval_seconds
    while True:
        time.sleep(max(0, next_time - time.time()))
        try:
            poller.poll()
        except Exception as e:
            logger.exception(f"Failed to run consumption poll to completion: {e}")
        next_time += (time.time() - next_time) // delay * delay + delay


every(polling_interval_seconds, poller.poll())

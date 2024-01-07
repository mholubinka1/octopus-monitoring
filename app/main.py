import argparse
import logging.config
from asyncio import sleep
from datetime import datetime
from logging import Logger, getLogger

from app.common.constants import APP_LOGGER_NAME
from app.common.logging import config
from app.data.api import OctopusAPI
from app.data.extract import (
    extract_consumption_history,
    extract_month_to_date_consumption,
    extract_new_consumption,
    extract_yesterday_consumption,
)
from app.data.influx import InfluxDB
from app.startup import get_api_settings, parse_api_settings

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

parser = argparse.ArgumentParser()
parser.add_argument("--config-file")
args = parser.parse_args()

settings = get_api_settings(args)
(api_key, electricity, gas) = parse_api_settings(args)
api = OctopusAPI(api_key, electricity, gas)

# add logging

influxdb = InfluxDB(settings)

latest_period_to, consumption_history = extract_consumption_history(api)
yesterday = extract_yesterday_consumption(api)
month_to_date = extract_month_to_date_consumption(api)

influxdb.save_consumption(consumption_history, yesterday, month_to_date)

last_retrieved_hour = datetime.utcnow().hour
period_from = latest_period_to
while not sleep(60):
    current_hour = datetime.utcnow().hour
    if not last_retrieved_hour == current_hour:
        period_from, new_consumption = extract_new_consumption(api, period_from)
        yesterday = extract_yesterday_consumption(api)
        month_to_date = extract_month_to_date_consumption(api)

        influxdb.save_consumption(new_consumption, yesterday, month_to_date)


##read and save all data up to now to database
##tz to be converted to UTC
##save last received timestamp

## read all data to last received on an hourly basis - after the next hour has struck

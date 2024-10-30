import argparse
import datetime
import logging.config
import sys
import time
from datetime import datetime as dt
from datetime import timedelta
from logging import Logger, getLogger

from common.config import get_settings
from common.logging import APP_LOGGER_NAME, config
from data.base import MonitoringClient
from data.consumption import ConsumptionRetriever
from data.pricing import PricingRetriever
from schedule import every, repeat, run_pending

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

logger.info("Starting octopus-monitoring.")

try:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-file")
    args = parser.parse_args()
    settings = get_settings(config_file_path=args.config_file)
    refresh_config = settings.refresh_settings
    logger.info("Startup complete.")
except Exception as e:
    logger.critical(f"Error loading startup configurations: {e}.")
    sys.exit(1)

logger.info(f"Consumption data update interval {refresh_config.refresh_interval}.")

client = MonitoringClient(settings)

consumption = ConsumptionRetriever(client)
pricing = PricingRetriever(client)


def startup(consumption: ConsumptionRetriever, pricing: PricingRetriever) -> None:
    current_time = dt.now(datetime.UTC)
    limit = (current_time - timedelta(days=refresh_config.historical_limit)).date()
    limit_dt = dt(limit.year, limit.month, limit.day, tzinfo=datetime.UTC)
    logger.info(f"Startup. Retrieving consumption history from {limit_dt}.")
    consumption.retrieve(period_from=limit_dt)
    pass


startup(consumption, pricing)


# @repeat(every(refresh_config.refresh_interval).hours, client, consumption, pricing)
@repeat(every(60).seconds, client, consumption, pricing)
def refresh(consumption: ConsumptionRetriever, pricing: PricingRetriever) -> None:
    consumption.refresh()


while True:
    run_pending()
    time.sleep(1)

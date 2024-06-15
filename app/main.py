import argparse
import datetime
import logging.config
import sys
from datetime import datetime as dt
from logging import Logger, getLogger

from common.config import get_settings
from common.logging import APP_LOGGER_NAME, config
from data.base import MonitoringClient
from data.consumption import ConsumptionRetriever
from data.poll import Poller, every
from data.pricing import PricingRetriever

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

try:
    client = MonitoringClient(settings)
    consumption = ConsumptionRetriever(client)
    pricing = PricingRetriever(client)
    logger.info(
        f"Consumption data update interval {refresh_config.update_interval} and polling interval: {refresh_config.polling_interval} seconds."
    )
    polling_start_time = dt.now(datetime.UTC)
    poller = Poller(refresh_config, consumption, pricing)
    logger.info("Starting periodic retrieval service.")
    every(refresh_config.polling_interval, poller.poll())
    sys.exit(0)
except Exception as e:
    logger.critical(f"Unexpected application error: {e}.")
    sys.exit(1)

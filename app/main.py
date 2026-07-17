import argparse
import datetime
import logging.config
import sys
import time
from datetime import datetime as dt
from datetime import timedelta
from logging import Logger, getLogger
from typing import Callable

from common.config import RefreshSettings, get_settings
from common.logging import APP_LOGGER_NAME, config
from data.base import MonitoringClient
from data.consumption import ConsumptionRetriever
from data.mysql.client import MariaDBClient
from data.pricing import PricingRetriever
from schedule import Job, Scheduler, default_scheduler

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

CONSUMPTION_REFRESH_JOB = "consumption_refresh"
PRICING_REFRESH_JOB = "pricing_refresh"


def startup(
    consumption: ConsumptionRetriever,
    refresh_config: RefreshSettings,
) -> None:
    current_time = dt.now(datetime.UTC)
    limit = (current_time - timedelta(days=refresh_config.historical_limit)).date()
    limit_dt = dt(limit.year, limit.month, limit.day, tzinfo=datetime.UTC)
    logger.info(f"Startup. Retrieving consumption history from {limit_dt}.")
    consumption.retrieve(period_from=limit_dt)


def _schedule_refresh_job(
    scheduler: Scheduler,
    refresh_config: RefreshSettings,
    job_name: str,
    refresh_fn: Callable[[], None],
    mariadb: MariaDBClient,
) -> Job:
    def refresh() -> None:
        try:
            refresh_fn()
            mariadb.record_job_run(job_name, "success")
        except Exception as e:
            mariadb.record_job_run(job_name, "failure", error=str(e))
            raise

    return scheduler.every(refresh_config.refresh_interval).hours.do(refresh)


def register_jobs(
    scheduler: Scheduler,
    refresh_config: RefreshSettings,
    consumption: ConsumptionRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler, refresh_config, CONSUMPTION_REFRESH_JOB, consumption.refresh, mariadb
    )


def register_pricing_job(
    scheduler: Scheduler,
    refresh_config: RefreshSettings,
    pricing: PricingRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler, refresh_config, PRICING_REFRESH_JOB, pricing.refresh, mariadb
    )


def run_pending_safely(scheduler: Scheduler) -> None:
    try:
        scheduler.run_pending()
    except Exception:
        logger.exception("Unhandled error while running scheduled jobs.")


def main() -> None:
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

    startup(consumption, refresh_config)
    pricing.refresh()
    register_jobs(default_scheduler, refresh_config, consumption, client.mariadb)
    register_pricing_job(default_scheduler, refresh_config, pricing, client.mariadb)

    while True:
        run_pending_safely(default_scheduler)
        time.sleep(1)


if __name__ == "__main__":
    main()

import argparse
import datetime
import logging.config
import sys
import threading
import time
from datetime import datetime as dt
from datetime import timedelta
from logging import Logger, getLogger
from typing import Callable, Optional

from common.config import RefreshSettings, get_settings
from common.decorator import retry_with_exponential_backoff
from common.logging import APP_LOGGER_NAME, config
from data.base import MonitoringClient
from data.consumption import ConsumptionRetriever
from data.consumption_summary import (
    ConsumptionSummaryBackfill,
    ConsumptionSummaryRetriever,
)
from data.cost_forecast import CostForecastRetriever
from data.mysql.client import MariaDBClient
from data.pricing import PricingRetriever
from schedule import Job, Scheduler, default_scheduler

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

CONSUMPTION_REFRESH_JOB = "consumption_refresh"
PRICING_REFRESH_JOB = "pricing_refresh"
WEEKLY_CONSUMPTION_SUMMARY_JOB = "update_consumption_summary"
YEARLY_COMPARISON_BACKFILL_JOB = "yearly_comparison_backfill"
COST_FORECAST_REFRESH_JOB = "cost_forecast_refresh"
DAILY_JOB_TIME = "04:00"  # shared by every daily/weekly-cadence job, so
# none of them land in watchtower's 03:00 update window -- that schedule is
# configured on the Pi host (pi-desktop's compose stack), not in this repo's
# docker-compose.yml, which only enables watchtower via container labels.


def startup(
    consumption: ConsumptionRetriever,
    refresh_config: RefreshSettings,
) -> None:
    current_time = dt.now(datetime.UTC)
    limit = (current_time - timedelta(days=refresh_config.retention)).date()
    limit_dt = dt(limit.year, limit.month, limit.day, tzinfo=datetime.UTC)
    logger.info(f"Startup. Retrieving consumption history from {limit_dt}.")
    consumption.retrieve(period_from=limit_dt)


def run_initial_pricing_sync(pricing: PricingRetriever) -> None:
    try:
        pricing.refresh()
    except Exception:
        logger.exception("Pricing sync failed at startup; continuing.")


def run_initial_consumption_summary_sync(
    consumption_summary: ConsumptionSummaryRetriever,
) -> None:
    try:
        consumption_summary.refresh()
    except Exception:
        logger.exception("Consumption summary sync failed at startup; continuing.")


def run_initial_cost_forecast_sync(cost_forecast: CostForecastRetriever) -> None:
    try:
        cost_forecast.refresh()
    except Exception:
        logger.exception("Cost forecast sync failed at startup; continuing.")


def _run_with_backoff_in_background(
    job_name: str,
    refresh_fn: Callable[[], None],
    mariadb: MariaDBClient,
) -> Callable[[], threading.Thread]:
    """Returns a callable that starts (or reuses) a background worker thread
    running refresh_fn with retry-with-backoff, recording the outcome as a
    job_run. Skips starting a new worker if one is already running."""
    worker: Optional[threading.Thread] = None

    @retry_with_exponential_backoff()
    def attempt_with_backoff() -> None:
        try:
            refresh_fn()
            mariadb.record_job_run(job_name, "success")
        except Exception as e:
            mariadb.record_job_run(job_name, "failure", error=str(e))
            raise RuntimeError(f"{job_name} failed: {e}") from e

    def run() -> threading.Thread:
        nonlocal worker
        if worker is not None and worker.is_alive():
            logger.info(f"{job_name} is still running; skipping this invocation.")
            return worker
        worker = threading.Thread(target=attempt_with_backoff, daemon=True)
        worker.start()
        return worker

    return run


def _schedule_refresh_job(
    scheduler: Scheduler,
    schedule_interval: Callable[[Scheduler], Job],
    job_name: str,
    refresh_fn: Callable[[], None],
    mariadb: MariaDBClient,
) -> Job:
    refresh = _run_with_backoff_in_background(job_name, refresh_fn, mariadb)
    return schedule_interval(scheduler).do(refresh)


def run_backfill_at_startup(
    backfill: ConsumptionSummaryBackfill, mariadb: MariaDBClient
) -> Optional[threading.Thread]:
    if mariadb.has_successful_job_run(YEARLY_COMPARISON_BACKFILL_JOB):
        logger.info("Yearly comparison backfill already completed; skipping.")
        return None
    run = _run_with_backoff_in_background(
        YEARLY_COMPARISON_BACKFILL_JOB, backfill.run, mariadb
    )
    return run()


def register_jobs(
    scheduler: Scheduler,
    refresh_config: RefreshSettings,
    consumption: ConsumptionRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler,
        lambda s: s.every(refresh_config.refresh_interval).hours,
        CONSUMPTION_REFRESH_JOB,
        consumption.refresh,
        mariadb,
    )


def register_pricing_job(
    scheduler: Scheduler,
    refresh_config: RefreshSettings,
    pricing: PricingRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler,
        lambda s: s.every(refresh_config.refresh_interval).hours,
        PRICING_REFRESH_JOB,
        pricing.refresh,
        mariadb,
    )


def register_consumption_summary_job(
    scheduler: Scheduler,
    consumption_summary: ConsumptionSummaryRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler,
        lambda s: s.every().monday.at(DAILY_JOB_TIME),
        WEEKLY_CONSUMPTION_SUMMARY_JOB,
        consumption_summary.refresh,
        mariadb,
    )


def register_cost_forecast_refresh_job(
    scheduler: Scheduler,
    cost_forecast: CostForecastRetriever,
    mariadb: MariaDBClient,
) -> Job:
    return _schedule_refresh_job(
        scheduler,
        lambda s: s.every().day.at(DAILY_JOB_TIME),
        COST_FORECAST_REFRESH_JOB,
        cost_forecast.refresh,
        mariadb,
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
    consumption_summary = ConsumptionSummaryRetriever(client.mariadb)
    yearly_comparison_backfill = ConsumptionSummaryBackfill(client)
    cost_forecast = CostForecastRetriever(client)

    startup(consumption, refresh_config)
    run_initial_pricing_sync(pricing)
    # The backfill (background thread) and this eager sync (foreground) can
    # both upsert the same recent (energy, date) row concurrently on first
    # startup. Harmless: both compute the same correct total from the same
    # underlying consumption rows, so whichever writes last is still right.
    run_backfill_at_startup(yearly_comparison_backfill, client.mariadb)
    run_initial_consumption_summary_sync(consumption_summary)
    run_initial_cost_forecast_sync(cost_forecast)
    register_jobs(default_scheduler, refresh_config, consumption, client.mariadb)
    register_pricing_job(default_scheduler, refresh_config, pricing, client.mariadb)
    register_consumption_summary_job(
        default_scheduler, consumption_summary, client.mariadb
    )
    register_cost_forecast_refresh_job(default_scheduler, cost_forecast, client.mariadb)

    while True:
        run_pending_safely(default_scheduler)
        time.sleep(1)


if __name__ == "__main__":
    main()

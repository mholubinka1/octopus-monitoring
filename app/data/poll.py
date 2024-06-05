import datetime
import logging.config
import time
from datetime import datetime as dt
from datetime import timedelta
from logging import Logger, getLogger
from typing import Any, Callable

from common.config import RefreshSettings
from common.logging import APP_LOGGER_NAME, config
from data.consumption import ConsumptionRetriever
from data.pricing import PricingRetriever

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def every(delay: int, poll: Callable) -> None:
    next_time = time.time() + delay
    while True:
        time.sleep(max(0, next_time - time.time()))
        try:
            poll()
        except Exception as e:
            logger.exception(f"Failed to run consumption poll: {e}")
        next_time += (time.time() - next_time) // delay * delay + delay


class Poller:
    _refresh_interval_seconds: int
    _last_retrieved_time: dt

    _initial_retrieval: bool

    _consumption_retriever: ConsumptionRetriever

    def __init__(
        self,
        refresh_settings: RefreshSettings,
        consumption: ConsumptionRetriever,
        pricing: PricingRetriever,
    ) -> None:
        self._refresh_interval_seconds = refresh_settings.update_interval
        self._consumption_retriever = consumption
        self._pricing = pricing
        self._initial_retrieval = True

    def poll(self) -> Any:
        current_time = dt.now(datetime.UTC)
        if self._initial_retrieval:
            logging.info("Initial run. Retrieving entire consumption history.")
            self._consumption_retriever.retrieve_consumption()
            self._last_retrieved_time = current_time
            self._initial_retrieval = False
            return

        polling_delta = (current_time - self._last_retrieved_time).seconds
        if polling_delta > self._refresh_interval_seconds:
            logging.info(
                "Update interval threshold reached, retrieving any new consumption data."
            )
            self._consumption_retriever.retrieve_latest_consumption()
            self._last_retrieved_time = current_time
            logging.info(
                f"New consumption data will be retrieved after {(current_time + timedelta(seconds=3600)).replace(minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return

        logging.debug("Update interval threshold not reached, waiting to poll again.")
        return

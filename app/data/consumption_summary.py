import logging.config
from datetime import datetime, timezone
from logging import Logger, getLogger

from common.logging import APP_LOGGER_NAME, config
from data.mysql.client import MariaDBClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class ConsumptionSummaryRetriever:
    _mariadb: MariaDBClient

    def __init__(self, mariadb: MariaDBClient) -> None:
        self._mariadb = mariadb

    def refresh(self) -> None:
        as_of = datetime.now(timezone.utc).date()
        summaries = self._mariadb.read_consumption_summarization_window(as_of)
        self._mariadb.write_consumption_summary(summaries)
        logger.info(f"Consumption summary refresh: {len(summaries)} day(s) summarized.")

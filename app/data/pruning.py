import logging.config
from datetime import UTC, datetime, timedelta
from logging import Logger, getLogger

from common.logging import APP_LOGGER_NAME, config
from data.mysql.client import MariaDBClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class DataPruner:
    _mariadb: MariaDBClient
    _retention_days: int

    def __init__(self, mariadb: MariaDBClient, retention_days: int) -> None:
        self._mariadb = mariadb
        self._retention_days = retention_days

    def run(self, as_of: datetime | None = None) -> None:
        if as_of is None:
            as_of = datetime.now(UTC)
        cutoff = as_of - timedelta(days=self._retention_days)
        deleted_consumption = self._mariadb.prune_consumption_older_than(cutoff)
        deleted_rates = self._mariadb.prune_product_rates_older_than(cutoff)
        logger.info(
            f"Pruned {deleted_consumption} consumption row(s) and "
            f"{deleted_rates} product_rate row(s) older than {cutoff}."
        )

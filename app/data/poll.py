import logging.config
from datetime import datetime, timedelta
from logging import Logger, getLogger

from common.constants import APP_LOGGER_NAME
from common.logging import config
from data.api import OctopusAPI
from data.extract import write_new_consumption_history
from data.influx import InfluxDB

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class ConsumptionPoller:
    api: OctopusAPI
    influxdb: InfluxDB

    period_from: datetime
    last_retrieved_hour: int

    def __init__(
        self,
        api: OctopusAPI,
        influxdb: InfluxDB,
        period_from: datetime,
        last_retrieved_hour: int,
    ) -> None:
        self.api = api
        self.influxdb = influxdb

        self.period_from = period_from
        self.last_retrieved_hour = last_retrieved_hour

    def poll(self) -> None:
        current_time = datetime.utcnow()
        if not self.last_retrieved_hour == current_time.hour:
            logging.info(
                "Update interval threshold reached, retrieving any new consumption data..."
            )
            self.period_from = write_new_consumption_history(
                self.period_from, self.api, self.influxdb
            )
            self.last_retrieved_hour = current_time.hour
            logging.info(
                f"New consumption will be retrieved after {(current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')}"
            )

        logging.debug("Update interval threshold not reached, waiting to poll again.")

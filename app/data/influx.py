import logging
import logging.config
from logging import Logger, getLogger
from typing import Dict, List

from common.constants import APP_LOGGER_NAME
from common.logging import config
from data.api import Consumption
from influxdb import InfluxDBClient

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class InfluxDB:
    client: InfluxDBClient

    def __init__(self, settings: Dict) -> None:
        host = settings["influx"]["host"]
        port = settings["influx"]["port"]
        database = settings["influx"]["database"]
        user = settings["influx"]["user"]
        password = settings["influx"]["password"]

        self.client = InfluxDBClient(host, port, user, password, database)
        logger.info(f"InfluxDB Client initialised. Writing data to: {database}")

    def create_points(
        self,
        half_hour_consumptions: List[Consumption],
        yesterday: List[Consumption],
        month_to_date: List[Consumption],
    ) -> List[Dict]:
        points: List[Dict] = list()
        for point in half_hour_consumptions:
            measurement = point.fuel.name.lower()

            month = point.end.month
            weeknumber = int(point.end.strftime("%W"))
            weekday = point.end.weekday()
            hour = point.end.hour

            consumption = point.consumption
            yesterday_consumption = next(
                (x for x in yesterday if x.fuel == point.fuel), None
            )
            yesterday_consumption = (
                yesterday_consumption.consumption if yesterday_consumption else None
            )

            month_to_date_consumption = next(
                (x for x in month_to_date if x.fuel == point.fuel), None
            )
            month_to_date_consumption = (
                month_to_date_consumption.consumption
                if month_to_date_consumption
                else None
            )

            # timestamp_ns = int(point.end.timestamp() * 1e9)

            data_point = {
                "measurement": measurement,
                "tags": {
                    "month": month,
                    "weeknumber": weeknumber,
                    "weekday": weekday,
                    "hour": hour,
                },
                "time": point.end,
                "fields": {
                    "consumption": consumption,
                    "yesterday": yesterday_consumption,
                    "month_to_date": month_to_date_consumption,
                },
            }
            points.append(data_point)
        return points

    def save_consumption(
        self,
        consumption: List[Consumption],
        yesterday: List[Consumption],
        month_to_date: List[Consumption],
    ) -> None:
        points = self.create_points(consumption, yesterday, month_to_date)
        result = self.client.write_points(points)
        logger.info(
            f"{len(points)} measurements successfully written to Influx database. {result}"
        )
        return

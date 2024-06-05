"""
import logging
import logging.config
from logging import Logger, getLogger
from typing import Dict, List

from common.logging import APP_LOGGER_NAME, config
from data.time import Duration, Month, Weekday

from data.octopus.api import Consumption, Fuel
from data.octopus.calc import to_kwh

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class InfluxDB:
    client: InfluxV2Client

    def __init__(self, settings: Dict) -> None:
        host = settings["influx"]["host"]
        port = settings["influx"]["port"]
        database = settings["influx"]["database"]
        user = settings["influx"]["user"]
        password = settings["influx"]["password"]

        self.client = InfluxDBClient(host, port, user, password, database)
        logger.info(f"InfluxDB Client initialised. Writing data to: {database}")

    def create_consumption_points(
        self,
        half_hour_consumptions: List[Consumption],
    ) -> List[Dict]:
        points: List[Dict] = list()
        for point in half_hour_consumptions:
            fuel = point.fuel.name.lower()

            month = Month(point.end.month)
            weeknumber = int(point.end.strftime("%W"))
            weekday = Weekday(point.end.weekday())
            hour = point.end.hour

            consumption = point.consumption
            approx_unit = (
                consumption
                if point.fuel == Fuel.ELECTRICITY
                else to_kwh(consumption, 39.5)
            )
            approx_cost = tariff.calculate_approximate_cost(point, approx_unit)

            influx_data_point = {
                "measurement": "granular",
                "tags": {
                    "fuel": fuel,
                    "month": month,
                    "weeknumber": weeknumber,
                    "weekday": weekday,
                    "hour": hour,
                },
                "time": point.start,
                "fields": {
                    "consumption": consumption,
                    "approx_units": approx_unit,
                    "approx_cost": approx_cost,
                },
            }
            points.append(influx_data_point)
        return points

    def create_cumulative_points(
        self,
        duration: Duration,
        periods: List[Consumption],
    ) -> List[Dict]:
        points: List[Dict] = list()
        for point in periods:
            fuel = point.fuel.name.lower()

            consumption = point.consumption
            approx_units = (
                consumption
                if point.fuel == Fuel.ELECTRICITY
                else to_kwh(consumption, 39.5)
            )
            approx_cost = tariff.calculate_approximate_cost(point, approx_unit)

            influx_data_point = {
                "measurement": "cumulative",
                "tags": {"fuel": fuel, "period": duration.name.lower()},
                "time": point.start,
                "fields": {
                    "consumption": consumption,
                    "approx_units": approx_units,
                    "approx_cost": approx_cost,
                },
            }
            points.append(influx_data_point)
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
            f"{len(points)} measurements successfully written to Influx database."
        )
        return
"""

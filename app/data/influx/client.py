import logging.config
from logging import Logger, getLogger
from typing import List

from common.config import InfluxV2Settings
from common.logging import APP_LOGGER_NAME, config
from data.model import Consumption, get_raw_unit, to_estimated_kwh
from data.octopus.model import Meter
from influxdb_client import InfluxDBClient, Point, WriteApi
from influxdb_client.client.write_api import SYNCHRONOUS

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class InfluxV2Client:
    _client: InfluxDBClient
    _write_api: WriteApi

    _energy_bucket: str

    def __init__(self, settings: InfluxV2Settings) -> None:
        self._client = InfluxDBClient(
            url=settings.url,
            token=settings.token,
            org=settings.organization,
        )
        self._energy_bucket = settings.bucket
        self.write_api = self._client.write_api(write_options=SYNCHRONOUS)

    def write_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        for measurement in consumption:
            p = (
                Point(measurement_name="consumption")
                .time(measurement.end)
                .tag("energy", meter.energy.name)
                .tag("duration", (measurement.end - measurement.start).seconds / 60)
                .tag("unit", get_raw_unit(meter.energy))
                .field("raw", measurement.raw)
                .field("est_kwh", to_estimated_kwh(meter.energy, measurement.raw))
            )
            _ = self.write_api.write(bucket=self._energy_bucket, record=p)
        logger.debug(
            f"Consumption data written to InfluxDB: {len(consumption)} points."
        )
        return

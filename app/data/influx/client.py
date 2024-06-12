from typing import List

from common.config import InfluxV2Settings
from data.model import Consumption
from data.octopus.model import Meter
from influxdb_client import InfluxDBClient, Point, WriteApi
from influxdb_client.client.write_api import SYNCHRONOUS


class InfluxV2Client:
    _client: InfluxDBClient
    _write_api: WriteApi

    _energy_bucket: str

    def __init__(self, settings: InfluxV2Settings) -> None:
        self._client = InfluxDBClient(
            url=settings.url,
            token=settings.organization,
            org=settings.token,
        )
        self._energy_bucket = settings.bucket
        self.write_api = self._client.write_api(write_options=SYNCHRONOUS)

    def write_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        for measurement in consumption:
            p = Point(measurement_name=consumption).time()
            _ = self.write_api.write(bucket=self._energy_bucket, record=p)
        return

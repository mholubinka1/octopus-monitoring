from typing import List

from common.config import ApplicationSettings
from data.influx.client import InfluxV2Client
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Account, Meter


class MonitoringClient:
    octopus: OctopusEnergyAPIClient
    influx: InfluxV2Client
    mariadb: MariaDBClient

    account: Account
    meters: List[Meter]
    region_code: str

    def __init__(self, settings: ApplicationSettings) -> None:
        self.octopus = OctopusEnergyAPIClient(settings.octopus)
        self.influx = InfluxV2Client(settings.influxdb)
        self.mariadb = MariaDBClient(settings.mariadb)

        (account, meters) = self.octopus.get_account_meter_information()
        self.account = account
        self.meters = meters

        self.region_code = self.octopus.get_region_code(self.account.postcode)

    def refresh_meters(
        self,
    ) -> None:
        (_, meters) = self.octopus.get_account_meter_information()
        self.meters = meters
        return

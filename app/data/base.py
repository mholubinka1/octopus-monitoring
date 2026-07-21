from datetime import datetime
from typing import List, Optional, Tuple

from common.config import ApplicationSettings
from data.model import Consumption, ConsumptionSummary, Energy
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Account, Agreement, Meter, Product, Rate


class MonitoringClient:
    octopus: OctopusEnergyAPIClient
    mariadb: MariaDBClient

    account: Account
    meters: List[Meter]
    region_code: str

    def __init__(self, settings: ApplicationSettings) -> None:
        self.octopus = OctopusEnergyAPIClient(settings.octopus)
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

    def fetch_consumption(
        self, meter: Meter, period_from: datetime
    ) -> Tuple[Optional[str], List[Consumption]]:
        return self.octopus.get_consumption(meter, period_from)

    def fetch_consumption_page(
        self, energy: Energy, next_page: str
    ) -> Tuple[Optional[str], List[Consumption]]:
        return self.octopus.get_consumption_directly_from_endpoint(energy, next_page)

    def persist_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        self.mariadb.write_consumption(meter, consumption)

    def persist_consumption_summary(self, summaries: List[ConsumptionSummary]) -> None:
        self.mariadb.write_consumption_summary(summaries)

    def persist_agreement(self, meter: Meter, agreements: List[Agreement]) -> None:
        self.mariadb.write_agreement(meter, agreements)

    def fetch_products(self) -> List[Product]:
        return self.octopus.get_products()

    def is_product_available_in_region(self, product_code: str, region: str) -> bool:
        return self.octopus.get_product_region_availability(product_code, region)

    def persist_product(self, product: Product) -> None:
        self.mariadb.write_product(product)

    def fetch_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]:
        return self.octopus.get_electricity_rates(
            product_code, tariff_code, period_from, period_to
        )

    def fetch_gas_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]:
        return self.octopus.get_gas_rates(
            product_code, tariff_code, period_from, period_to
        )

    def persist_rate(self, product_code: str, region: str, rates: List[Rate]) -> None:
        self.mariadb.write_product_rate(product_code, region, rates)

    def fetch_electricity_tariff_code(
        self, product_code: str, region: str
    ) -> Optional[str]:
        return self.octopus.get_electricity_tariff_code(product_code, region)

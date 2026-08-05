from datetime import datetime

from common.config import ApplicationSettings
from data.model import (
    Consumption,
    ConsumptionSummary,
    CostForecast,
    DailyCostSummary,
    Energy,
)
from data.mysql.client import MariaDBClient
from data.octopus.agile_predict import AgilePredictClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.kraken import BillingPeriodClient, KrakenTransport
from data.octopus.model import (
    Account,
    AgileForecastReading,
    Agreement,
    BillingPeriod,
    Meter,
    Product,
    Rate,
)
from data.octopus.x2r import X2rClient


class MonitoringClient:
    octopus: OctopusEnergyAPIClient
    mariadb: MariaDBClient
    _billing_period: BillingPeriodClient
    _agile_predict: AgilePredictClient
    _x2r: X2rClient

    account: Account
    meters: list[Meter]
    region_code: str

    def __init__(self, settings: ApplicationSettings) -> None:
        self.octopus = OctopusEnergyAPIClient(settings.octopus)
        self.mariadb = MariaDBClient(settings.mariadb)
        self._billing_period = BillingPeriodClient(settings.octopus, KrakenTransport())
        self._agile_predict = AgilePredictClient()
        self._x2r = X2rClient()

        account, meters = self.octopus.get_account_meter_information()
        self.account = account
        self.meters = meters

        self.region_code = self.octopus.get_region_code(self.account.postcode)

    def refresh_meters(
        self,
    ) -> None:
        _, meters = self.octopus.get_account_meter_information()
        self.meters = meters

    def fetch_consumption(
        self, meter: Meter, period_from: datetime
    ) -> tuple[str | None, list[Consumption]]:
        return self.octopus.get_consumption(meter, period_from)

    def fetch_consumption_page(
        self, energy: Energy, next_page: str
    ) -> tuple[str | None, list[Consumption]]:
        return self.octopus.get_consumption_directly_from_endpoint(energy, next_page)

    def persist_consumption(self, meter: Meter, consumption: list[Consumption]) -> None:
        self.mariadb.write_consumption(meter, consumption)

    def persist_consumption_summary(self, summaries: list[ConsumptionSummary]) -> None:
        self.mariadb.write_consumption_summary(summaries)

    def persist_agreement(self, meter: Meter, agreements: list[Agreement]) -> None:
        self.mariadb.write_agreement(meter, agreements)

    def fetch_products(self) -> list[Product]:
        return self.octopus.get_products()

    def is_product_available_in_region(self, product_code: str, region: str) -> bool:
        return self.octopus.get_product_region_availability(product_code, region)

    def persist_product(self, product: Product) -> None:
        self.mariadb.write_product(product)

    def fetch_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: datetime | None,
        period_to: datetime | None,
    ) -> list[Rate]:
        return self.octopus.get_electricity_rates(
            product_code, tariff_code, period_from, period_to
        )

    def fetch_gas_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: datetime | None,
        period_to: datetime | None,
    ) -> list[Rate]:
        return self.octopus.get_gas_rates(
            product_code, tariff_code, period_from, period_to
        )

    def persist_rate(self, product_code: str, region: str, rates: list[Rate]) -> None:
        self.mariadb.write_product_rate(product_code, region, rates)

    def fetch_electricity_tariff_code(
        self, product_code: str, region: str
    ) -> str | None:
        return self.octopus.get_electricity_tariff_code(product_code, region)

    def get_current_billing_period(self) -> BillingPeriod:
        return self._billing_period.get_current_billing_period()

    def fetch_agile_forecast(self, region: str) -> list[AgileForecastReading]:
        return self._agile_predict.get_forecast(region)

    def fetch_agile_forecast_fallback(self, region: str) -> list[AgileForecastReading]:
        return self._x2r.get_forecast(region)

    def persist_agile_forecast(
        self, region: str, readings: list[AgileForecastReading], fetched_at: datetime
    ) -> None:
        self.mariadb.write_agile_forecast(region, readings, fetched_at)

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime, region: str
    ) -> list[DailyCostSummary]:
        return self.mariadb.read_elapsed_billing_period_costs(
            period_from, period_to, region
        )

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Rate | None:
        return self.mariadb.read_current_product_rate(product_code, region, as_of)

    def persist_cost_forecast(self, forecast: CostForecast) -> None:
        self.mariadb.write_cost_forecast(forecast)

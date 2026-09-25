from datetime import datetime

from octopus_app.common.config import OctopusAPISettings
from octopus_app.data.model import Consumption, Energy
from octopus_app.data.octopus.account import AccountClient
from octopus_app.data.octopus.consumption import ConsumptionClient
from octopus_app.data.octopus.model import Account, Meter, Product, Rate
from octopus_app.data.octopus.product import ProductClient
from octopus_app.data.octopus.rate import RateClient
from octopus_app.data.octopus.transport import OctopusTransport


class OctopusEnergyAPIClient:
    def __init__(self, settings: OctopusAPISettings) -> None:
        transport = OctopusTransport(settings)
        self._account = AccountClient(settings, transport)
        self._product = ProductClient(transport)
        self._rate = RateClient(transport)
        self._consumption = ConsumptionClient(transport)

    # region Account Information

    def get_account_meter_information(self) -> tuple[Account, list[Meter]]:
        return self._account.get_account_meter_information()

    def get_region_code(self, postcode: str) -> str:
        return self._account.get_region_code(postcode)

    # endregion

    # region Pricing

    def get_products(self) -> list[Product]:
        return self._product.get_products()

    def get_products_directly_from_endpoint(
        self, api_endpoint: str
    ) -> tuple[str | None, list[Product]]:
        return self._product.get_products_directly_from_endpoint(api_endpoint)

    def get_product_region_availability(self, product_code: str, region: str) -> bool:
        return self._product.get_product_region_availability(product_code, region)

    def get_electricity_tariff_code(self, product_code: str, region: str) -> str | None:
        return self._product.get_electricity_tariff_code(product_code, region)

    def get_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[Rate]:
        return self._rate.get_electricity_rates(
            product_code, tariff_code, period_from, period_to
        )

    def get_gas_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[Rate]:
        return self._rate.get_gas_rates(
            product_code, tariff_code, period_from, period_to
        )

    # endregion

    # region Consumption

    def get_consumption(
        self, meter: Meter, period_from: datetime, period_to: datetime | None = None
    ) -> tuple[str | None, list[Consumption]]:
        return self._consumption.get_consumption(meter, period_from, period_to)

    def get_consumption_directly_from_endpoint(
        self, energy: Energy, api_endpoint: str
    ) -> tuple[str | None, list[Consumption]]:
        return self._consumption.get_consumption_directly_from_endpoint(
            energy, api_endpoint
        )

    # endregion

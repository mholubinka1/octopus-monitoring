from datetime import datetime
from typing import List, Optional, Protocol

from data.model import Energy
from data.octopus.model import Agreement, Meter, Product, Rate

EXPORT_DIRECTION = "EXPORT"


class PricingSource(Protocol):
    meters: List[Meter]
    region_code: str

    def refresh_meters(self) -> None: ...

    def persist_agreement(self, meter: Meter, agreements: List[Agreement]) -> None: ...

    def fetch_products(self) -> List[Product]: ...

    def is_product_available_in_region(
        self, product_code: str, region: str
    ) -> bool: ...

    def persist_product(self, product: Product) -> None: ...

    def fetch_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]: ...

    def persist_rate(
        self, product_code: str, region: str, rates: List[Rate]
    ) -> None: ...


class PricingRetriever:
    _client: PricingSource

    def __init__(self, client: PricingSource) -> None:
        self._client = client

    def refresh(self) -> None:
        self._client.refresh_meters()
        self._sync_agreements()
        self._sync_product_catalogue()
        self._sync_own_product_rates()

    def _sync_agreements(self) -> None:
        for meter in self._client.meters:
            self._client.persist_agreement(meter, meter.agreements)

    def _sync_product_catalogue(self) -> None:
        for product in self._client.fetch_products():
            if product.direction == EXPORT_DIRECTION:
                continue
            if not self._client.is_product_available_in_region(
                product.product_code, self._client.region_code
            ):
                continue
            self._client.persist_product(product)

    def _sync_own_product_rates(self) -> None:
        for meter in self._client.meters:
            if meter.energy != Energy.electricity:
                continue
            for agreement in meter.agreements:
                rates = self._client.fetch_electricity_rates(
                    agreement.product_code,
                    agreement.tariff_code,
                    agreement.valid_from,
                    agreement.valid_to,
                )
                self._client.persist_rate(
                    agreement.product_code, self._client.region_code, rates
                )

from typing import List, Protocol

from data.octopus.model import Agreement, Meter, Product

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


class PricingRetriever:
    _client: PricingSource

    def __init__(self, client: PricingSource) -> None:
        self._client = client

    def refresh(self) -> None:
        self._client.refresh_meters()
        self._sync_agreements()
        self._sync_product_catalogue()

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

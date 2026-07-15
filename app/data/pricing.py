from data.base import MonitoringClient

EXPORT_DIRECTION = "EXPORT"


class PricingRetriever:
    _client: MonitoringClient

    def __init__(self, client: MonitoringClient) -> None:
        self._client = client

    def refresh(self) -> None:
        self._client.refresh_meters()
        self._sync_agreements()
        self._sync_product_catalogue()

    def _sync_agreements(self) -> None:
        for meter in self._client.meters:
            self._client.mariadb.write_agreement(meter, meter.agreements)

    def _sync_product_catalogue(self) -> None:
        for product in self._client.octopus.get_products():
            if product.direction == EXPORT_DIRECTION:
                continue
            if not self._client.octopus.get_product_region_availability(
                product.product_code, self._client.region_code
            ):
                continue
            self._client.mariadb.write_product(product)

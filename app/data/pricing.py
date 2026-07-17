import logging.config
from datetime import datetime
from logging import Logger, getLogger
from typing import Iterator, List, Optional, Protocol, Tuple

from common.logging import APP_LOGGER_NAME, config
from data.model import Energy
from data.octopus.model import Agreement, Direction, Meter, MeterSource, Product, Rate

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


class PricingSource(MeterSource, Protocol):
    region_code: str

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

    def fetch_gas_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]: ...

    def persist_rate(
        self, product_code: str, region: str, rates: List[Rate]
    ) -> None: ...

    def fetch_electricity_tariff_code(
        self, product_code: str, region: str
    ) -> Optional[str]: ...


class PricingRetriever:
    _client: PricingSource

    def __init__(self, client: PricingSource) -> None:
        self._client = client

    def refresh(self) -> None:
        self._client.refresh_meters()
        self._sync_agreements()
        products = self._client.fetch_products()
        self._sync_product_catalogue(products)
        self._sync_own_product_rates()
        self._sync_comparison_rates(products)

    def _sync_agreements(self) -> None:
        for meter in self._client.meters:
            self._client.persist_agreement(meter, meter.agreements)

    def _sync_product_catalogue(self, products: List[Product]) -> None:
        for product in products:
            if product.direction == Direction.EXPORT:
                continue
            if not self._client.is_product_available_in_region(
                product.product_code, self._client.region_code
            ):
                continue
            self._client.persist_product(product)

    def _meter_agreement_pairs(self) -> Iterator[Tuple[Meter, Agreement]]:
        for meter in self._client.meters:
            for agreement in meter.agreements:
                yield meter, agreement

    def _sync_own_product_rates(self) -> None:
        for meter, agreement in self._meter_agreement_pairs():
            fetch_rates = (
                self._client.fetch_electricity_rates
                if meter.energy == Energy.electricity
                else self._client.fetch_gas_rates
            )
            rates = fetch_rates(
                agreement.product_code,
                agreement.tariff_code,
                agreement.valid_from,
                agreement.valid_to,
            )
            self._client.persist_rate(
                agreement.product_code, self._client.region_code, rates
            )

    def _sync_comparison_rates(self, products: List[Product]) -> None:
        own_product_codes = {
            agreement.product_code for _, agreement in self._meter_agreement_pairs()
        }
        for product in products:
            if product.direction == Direction.EXPORT:
                continue
            if product.product_code in own_product_codes:
                # Already synced with the agreement's actual tariff_code by
                # _sync_own_product_rates — re-fetching here would pick an
                # arbitrary billing method and risk overwriting the accurate
                # rate, since product_rate rows are keyed by product_code/
                # region/valid_from, not tariff_code.
                continue
            tariff_code = self._client.fetch_electricity_tariff_code(
                product.product_code, self._client.region_code
            )
            if tariff_code is None:
                logger.info(
                    f"No electricity rate published for {product.product_code} "
                    f"in region {self._client.region_code} — skipping."
                )
                continue
            rates = self._client.fetch_electricity_rates(
                product.product_code, tariff_code, None, None
            )
            self._client.persist_rate(
                product.product_code, self._client.region_code, rates
            )

from typing import Dict, List, Optional, Tuple

from data.octopus.model import Direction, Product
from data.octopus.transport import OctopusTransport
from pydantic import BaseModel


class ProductSummary(BaseModel):
    code: str
    display_name: str
    direction: str


class ProductListResponse(BaseModel):
    results: List[ProductSummary]
    next: Optional[str] = None


class ProductDetailResponse(BaseModel):
    single_register_electricity_tariffs: Dict[str, Dict] = {}
    dual_register_electricity_tariffs: Dict[str, Dict] = {}
    single_register_gas_tariffs: Dict[str, Dict] = {}


class ProductClient:
    def __init__(self, transport: OctopusTransport) -> None:
        self._transport = transport

    def get_products(self) -> List[Product]:
        products: List[Product] = []
        api_endpoint: Optional[str] = self._transport.base_url + "products/"
        while api_endpoint:
            (api_endpoint, page) = self.get_products_directly_from_endpoint(
                api_endpoint
            )
            products.extend(page)
        return products

    def get_products_directly_from_endpoint(
        self, api_endpoint: str
    ) -> Tuple[Optional[str], List[Product]]:
        parsed = self._transport.get(
            api_endpoint, ProductListResponse, description="fetch product catalogue"
        )
        products = [
            Product(
                product_code=summary.code,
                display_name=summary.display_name,
                direction=Direction(summary.direction),
            )
            for summary in parsed.results
        ]
        return (parsed.next, products)

    def get_product_region_availability(self, product_code: str, region: str) -> bool:
        api_endpoint = self._transport.base_url + f"products/{product_code}/"
        parsed = self._transport.get(
            api_endpoint,
            ProductDetailResponse,
            description=f"fetch product detail for {product_code}",
        )
        return (
            region in parsed.single_register_electricity_tariffs
            or region in parsed.dual_register_electricity_tariffs
            or region in parsed.single_register_gas_tariffs
        )

    def get_electricity_tariff_code(
        self, product_code: str, region: str
    ) -> Optional[str]:
        api_endpoint = self._transport.base_url + f"products/{product_code}/"
        parsed = self._transport.get(
            api_endpoint,
            ProductDetailResponse,
            description=f"fetch product detail for {product_code}",
        )
        billing_methods = parsed.single_register_electricity_tariffs.get(region)
        if not billing_methods:
            return None
        tariff = next(iter(billing_methods.values()), None)
        return tariff.get("code") if tariff else None

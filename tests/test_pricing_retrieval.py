from datetime import datetime, timezone
from typing import List, Optional

import responses
from common.config import OctopusAPISettings
from data.mysql import sql_models
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Agreement, Electricity, Gas, Meter, Product, Rate
from data.pricing import PricingRetriever

PRODUCTS_ENDPOINT = "https://api.octopus.energy/v1/products/"


class _RealPricingSource:
    """A real PricingSource adapter for tests: genuine OctopusEnergyAPIClient
    and MariaDBClient underneath, with meters/region_code fixed up front
    rather than fetched, so tests only need to mock the HTTP endpoints
    PricingRetriever.refresh() actually calls."""

    def __init__(
        self,
        octopus: OctopusEnergyAPIClient,
        mariadb: MariaDBClient,
        meters: List[Meter],
        region_code: str,
    ) -> None:
        self._octopus = octopus
        self._mariadb = mariadb
        self.meters = meters
        self.region_code = region_code

    def refresh_meters(self) -> None:
        pass

    def persist_agreement(self, meter: Meter, agreements: List[Agreement]) -> None:
        self._mariadb.write_agreement(meter, agreements)

    def fetch_products(self) -> List[Product]:
        return self._octopus.get_products()

    def is_product_available_in_region(self, product_code: str, region: str) -> bool:
        return self._octopus.get_product_region_availability(product_code, region)

    def persist_product(self, product: Product) -> None:
        self._mariadb.write_product(product)

    def fetch_electricity_rates(
        self,
        product_code: str,
        tariff_code: str,
        period_from: Optional[datetime],
        period_to: Optional[datetime],
    ) -> List[Rate]:
        return self._octopus.get_electricity_rates(
            product_code, tariff_code, period_from, period_to
        )

    def persist_rate(self, product_code: str, region: str, rates: List[Rate]) -> None:
        self._mariadb.write_product_rate(product_code, region, rates)


def _make_electricity_meter() -> Electricity:
    return Electricity(
        mpan="1234567890123",
        serial_number="00A1234567",
        agreements=[
            Agreement(
                tariff_code="E-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        ],
    )


def _make_gas_meter() -> Gas:
    return Gas(
        mprn="9876543210987",
        serial_number="00G7654321",
        agreements=[
            Agreement(
                tariff_code="G-1R-VAR-22-11-01-A",
                valid_from=datetime(2022, 11, 1, tzinfo=timezone.utc),
                valid_to=None,
            )
        ],
    )


def _make_source(
    mariadb_client: MariaDBClient, meters: List[Meter], region_code: str = "H"
) -> _RealPricingSource:
    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )
    return _RealPricingSource(octopus, mariadb_client, meters, region_code)


def _mock_own_product_rate_endpoints() -> None:
    responses.add(
        responses.GET,
        "https://api.octopus.energy/v1/products/VAR-22-11-01/electricity-tariffs/"
        "E-1R-VAR-22-11-01-A/standard-unit-rates/",
        json={
            "results": [
                {
                    "value_inc_vat": 24.53,
                    "valid_from": "2022-11-01T00:00:00Z",
                    "valid_to": "2022-11-01T00:30:00Z",
                }
            ],
            "next": None,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.octopus.energy/v1/products/VAR-22-11-01/electricity-tariffs/"
        "E-1R-VAR-22-11-01-A/standing-charges/",
        json={
            "results": [
                {
                    "value_inc_vat": 48.20,
                    "valid_from": "2022-11-01T00:00:00Z",
                    "valid_to": None,
                }
            ],
            "next": None,
        },
        status=200,
    )


@responses.activate
def test_refresh_persists_every_meters_agreements(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET, PRODUCTS_ENDPOINT, json={"results": [], "next": None}, status=200
    )
    _mock_own_product_rate_endpoints()
    electricity_meter = _make_electricity_meter()
    gas_meter = _make_gas_meter()
    source = _make_source(mariadb_client, [electricity_meter, gas_meter])

    PricingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.agreement).all()

    assert len(stored) == 2
    assert {row.energy for row in stored} == {"E", "G"}


@responses.activate
def test_refresh_persists_products_available_in_the_account_s_region(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT,
        json={
            "results": [
                {
                    "code": "VAR-22-11-01",
                    "display_name": "Flexible Octopus",
                    "direction": "IMPORT",
                },
                {
                    "code": "AGILE-24-10-01",
                    "display_name": "Agile Octopus",
                    "direction": "IMPORT",
                },
            ],
            "next": None,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT + "VAR-22-11-01/",
        json={
            "single_register_electricity_tariffs": {
                "H": {"direct_debit_monthly": {"code": "E-1R-VAR-22-11-01-H"}}
            }
        },
        status=200,
    )
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT + "AGILE-24-10-01/",
        json={"single_register_electricity_tariffs": {}},
        status=200,
    )
    source = _make_source(mariadb_client, [])

    PricingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product).all()

    assert [row.product_code for row in stored] == ["VAR-22-11-01"]


@responses.activate
def test_refresh_persists_the_account_s_own_product_electricity_rates(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET, PRODUCTS_ENDPOINT, json={"results": [], "next": None}, status=200
    )
    _mock_own_product_rate_endpoints()
    electricity_meter = _make_electricity_meter()
    source = _make_source(mariadb_client, [electricity_meter])

    PricingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product_rate).all()

    assert len(stored) == 1
    assert stored[0].product_code == "VAR-22-11-01"
    assert stored[0].region == "H"


@responses.activate
def test_refresh_does_not_fetch_rates_for_gas_meters(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET, PRODUCTS_ENDPOINT, json={"results": [], "next": None}, status=200
    )
    gas_meter = _make_gas_meter()
    source = _make_source(mariadb_client, [gas_meter])

    PricingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product_rate).all()

    assert stored == []


@responses.activate
def test_refresh_does_not_persist_export_products(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT,
        json={
            "results": [
                {
                    "code": "VAR-22-11-01",
                    "display_name": "Flexible Octopus",
                    "direction": "IMPORT",
                },
                {
                    "code": "OUTGOING-24-10-01",
                    "display_name": "Outgoing Octopus",
                    "direction": "EXPORT",
                },
            ],
            "next": None,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT + "VAR-22-11-01/",
        json={
            "single_register_electricity_tariffs": {
                "H": {"direct_debit_monthly": {"code": "E-1R-VAR-22-11-01-H"}}
            }
        },
        status=200,
    )
    source = _make_source(mariadb_client, [])

    PricingRetriever(source).refresh()

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product).all()

    assert [row.product_code for row in stored] == ["VAR-22-11-01"]

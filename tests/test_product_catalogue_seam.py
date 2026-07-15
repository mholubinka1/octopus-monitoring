import responses
from common.config import OctopusAPISettings
from data.mysql import sql_models
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient

PRODUCTS_ENDPOINT = "https://api.octopus.energy/v1/products/"
PRODUCT_DETAIL_ENDPOINT = "https://api.octopus.energy/v1/products/VAR-22-11-01/"


@responses.activate
def test_products_fetched_from_octopus_are_persisted_and_queryable(
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
                }
            ],
            "next": None,
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    products = octopus.get_products()
    for product in products:
        mariadb_client.write_product(product)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.product).all()

    assert len(stored) == 1
    assert stored[0].product_code == "VAR-22-11-01"
    assert stored[0].display_name == "Flexible Octopus"
    assert stored[0].direction == "IMPORT"


@responses.activate
def test_pagination_is_followed_to_completion() -> None:
    next_page_endpoint = PRODUCTS_ENDPOINT + "?page=2"
    responses.add(
        responses.GET,
        PRODUCTS_ENDPOINT,
        json={
            "results": [
                {
                    "code": "VAR-22-11-01",
                    "display_name": "Flexible Octopus",
                    "direction": "IMPORT",
                }
            ],
            "next": next_page_endpoint,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        next_page_endpoint,
        json={
            "results": [
                {
                    "code": "AGILE-24-10-01",
                    "display_name": "Agile Octopus",
                    "direction": "IMPORT",
                }
            ],
            "next": None,
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    products = octopus.get_products()

    assert [p.product_code for p in products] == ["VAR-22-11-01", "AGILE-24-10-01"]


@responses.activate
def test_a_product_available_in_the_account_s_region_is_reported_as_available() -> None:
    responses.add(
        responses.GET,
        PRODUCT_DETAIL_ENDPOINT,
        json={
            "single_register_electricity_tariffs": {
                "H": {"direct_debit_monthly": {"code": "E-1R-VAR-22-11-01-H"}}
            }
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    assert octopus.get_product_region_availability("VAR-22-11-01", "H") is True


@responses.activate
def test_a_product_not_available_in_the_account_s_region_is_reported_as_unavailable() -> (
    None
):
    responses.add(
        responses.GET,
        PRODUCT_DETAIL_ENDPOINT,
        json={
            "single_register_electricity_tariffs": {
                "H": {"direct_debit_monthly": {"code": "E-1R-VAR-22-11-01-H"}}
            }
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    assert octopus.get_product_region_availability("VAR-22-11-01", "A") is False

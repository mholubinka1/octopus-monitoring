from datetime import datetime, timezone
from unittest.mock import Mock

from data.octopus.model import Agreement, Electricity, Gas, Product
from data.pricing import PricingRetriever


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


def test_refresh_persists_every_meters_agreements() -> None:
    electricity_meter = _make_electricity_meter()
    gas_meter = _make_gas_meter()

    client = Mock()
    client.meters = [electricity_meter, gas_meter]
    client.octopus.get_products.return_value = []

    retriever = PricingRetriever(client)
    retriever.refresh()

    client.refresh_meters.assert_called_once()
    assert client.mariadb.write_agreement.call_count == 2
    client.mariadb.write_agreement.assert_any_call(
        electricity_meter, electricity_meter.agreements
    )
    client.mariadb.write_agreement.assert_any_call(gas_meter, gas_meter.agreements)


def test_refresh_persists_products_available_in_the_account_s_region() -> None:
    available_product = Product(
        product_code="VAR-22-11-01", display_name="Flexible Octopus", direction="IMPORT"
    )
    unavailable_product = Product(
        product_code="AGILE-24-10-01", display_name="Agile Octopus", direction="IMPORT"
    )

    client = Mock()
    client.meters = []
    client.region_code = "H"
    client.octopus.get_products.return_value = [available_product, unavailable_product]
    client.octopus.get_product_region_availability.side_effect = (
        lambda product_code, region: product_code == "VAR-22-11-01"
    )

    retriever = PricingRetriever(client)
    retriever.refresh()

    client.mariadb.write_product.assert_called_once_with(available_product)


def test_refresh_does_not_persist_export_products() -> None:
    import_product = Product(
        product_code="VAR-22-11-01", display_name="Flexible Octopus", direction="IMPORT"
    )
    export_product = Product(
        product_code="OUTGOING-24-10-01",
        display_name="Outgoing Octopus",
        direction="EXPORT",
    )

    client = Mock()
    client.meters = []
    client.region_code = "H"
    client.octopus.get_products.return_value = [import_product, export_product]
    client.octopus.get_product_region_availability.return_value = True

    retriever = PricingRetriever(client)
    retriever.refresh()

    client.mariadb.write_product.assert_called_once_with(import_product)

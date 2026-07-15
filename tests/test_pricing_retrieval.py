from datetime import datetime, timezone
from unittest.mock import Mock

from data.octopus.model import Agreement, Electricity, Gas
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

    retriever = PricingRetriever(client)
    retriever.refresh()

    client.refresh_meters.assert_called_once()
    assert client.mariadb.write_agreement.call_count == 2
    client.mariadb.write_agreement.assert_any_call(
        electricity_meter, electricity_meter.agreements
    )
    client.mariadb.write_agreement.assert_any_call(gas_meter, gas_meter.agreements)

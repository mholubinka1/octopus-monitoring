import pytest
import responses
from common.config import OctopusAPISettings
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Electricity

ACCOUNT_ENDPOINT = "https://api.octopus.energy/v1/accounts/A-1234ABCD"

VALID_ACCOUNT_RESPONSE = {
    "properties": [
        {
            "postcode": "AB1 2CD",
            "address_line_1": "1 Test Street",
            "address_line_2": "",
            "address_line_3": "",
            "town": "Testville",
            "county": "",
            "electricity_meter_points": [
                {
                    "mpan": "1234567890123",
                    "meters": [{"serial_number": "00A1234567"}],
                    "agreements": [
                        {
                            "tariff_code": "E-1R-VAR-22-11-01-A",
                            "valid_from": "2022-11-01T00:00:00+00:00",
                            "valid_to": None,
                        }
                    ],
                }
            ],
            "gas_meter_points": [],
        }
    ]
}


@responses.activate
def test_account_and_meters_are_fetched_from_octopus() -> None:
    responses.add(
        responses.GET, ACCOUNT_ENDPOINT, json=VALID_ACCOUNT_RESPONSE, status=200
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    account, meters = octopus.get_account_meter_information()

    assert account.number == "A-1234ABCD"
    assert account.postcode == "AB12CD"
    assert len(meters) == 1
    assert isinstance(meters[0], Electricity)
    assert meters[0].mpan == "1234567890123"
    assert meters[0].serial_number == "00A1234567"


@responses.activate
def test_account_response_missing_a_required_field_raises_a_clear_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    invalid_response = {
        "properties": [
            {
                "address_line_1": "1 Test Street",
                "address_line_2": "",
                "address_line_3": "",
                "town": "Testville",
                "county": "",
                "electricity_meter_points": [],
                "gas_meter_points": [],
            }
        ]
    }
    responses.add(responses.GET, ACCOUNT_ENDPOINT, json=invalid_response, status=200)

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(Exception) as exc_info:
        octopus.get_account_meter_information()

    assert "postcode" in str(exc_info.value)
    assert "field required" in str(exc_info.value).lower()

import pytest
import requests
import responses
from common.config import OctopusAPISettings
from common.exceptions import APIError
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Electricity

ACCOUNT_ENDPOINT = "https://api.octopus.energy/v1/accounts/A-1234ABCD"
GRID_SUPPLY_POINTS_ENDPOINT = (
    "https://api.octopus.energy/v1/industry/grid-supply-points"
)

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

    with pytest.raises(RuntimeError) as exc_info:
        octopus.get_account_meter_information()

    assert "postcode" in str(exc_info.value)
    assert "field required" in str(exc_info.value).lower()


@responses.activate
def test_account_meter_information_connection_failure_raises_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ACCOUNT_ENDPOINT,
        body=requests.exceptions.ConnectTimeout("connection timed out"),
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(RuntimeError, match="connection timed out"):
        octopus.get_account_meter_information()


@responses.activate
def test_account_meter_information_non_json_error_response_raises_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ACCOUNT_ENDPOINT,
        body="Internal Server Error",
        status=500,
        content_type="text/plain",
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(APIError, match="Internal Server Error"):
        octopus.get_account_meter_information()


@responses.activate
def test_region_code_is_fetched_for_a_postcode() -> None:
    responses.add(
        responses.GET,
        GRID_SUPPLY_POINTS_ENDPOINT,
        json={"results": [{"group_id": "_H"}]},
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    # The API returns "_H" (leading underscore); normalized to "H" to match
    # the bare-letter region format used by tariff codes and product maps.
    assert octopus.get_region_code("AB1 2CD") == "H"


@responses.activate
def test_a_region_code_without_a_leading_underscore_is_left_unchanged() -> None:
    responses.add(
        responses.GET,
        GRID_SUPPLY_POINTS_ENDPOINT,
        json={"results": [{"group_id": "H"}]},
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    assert octopus.get_region_code("AB1 2CD") == "H"


@responses.activate
def test_a_postcode_with_no_matching_grid_supply_point_raises_a_clear_error() -> None:
    responses.add(
        responses.GET,
        GRID_SUPPLY_POINTS_ENDPOINT,
        json={"results": []},
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(APIError, match="AB1 2CD"):
        octopus.get_region_code("AB1 2CD")

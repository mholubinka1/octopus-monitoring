from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests
import responses
from common.config import OctopusAPISettings
from data.octopus.api import OctopusEnergyAPIClient

PRODUCT_CODE = "VAR-22-11-01"
TARIFF_CODE = "G-1R-VAR-22-11-01-H"
UNIT_RATES_ENDPOINT = (
    f"https://api.octopus.energy/v1/products/{PRODUCT_CODE}/gas-tariffs/"
    f"{TARIFF_CODE}/standard-unit-rates/"
)
STANDING_CHARGES_ENDPOINT = (
    f"https://api.octopus.energy/v1/products/{PRODUCT_CODE}/gas-tariffs/"
    f"{TARIFF_CODE}/standing-charges/"
)


def _octopus() -> OctopusEnergyAPIClient:
    return OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )


@responses.activate
def test_gas_unit_rates_are_paired_with_the_standing_charge_in_effect() -> None:
    responses.add(
        responses.GET,
        UNIT_RATES_ENDPOINT,
        json={
            "results": [
                {
                    "value_inc_vat": 6.89,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-02T00:00:00Z",
                }
            ],
            "next": None,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        STANDING_CHARGES_ENDPOINT,
        json={
            "results": [
                {
                    "value_inc_vat": 29.11,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                }
            ],
            "next": None,
        },
        status=200,
    )

    rates = _octopus().get_gas_rates(PRODUCT_CODE, TARIFF_CODE)

    assert len(rates) == 1
    assert rates[0].unit_rate == Decimal("6.89")
    assert rates[0].standing_charge == Decimal("29.11")
    assert rates[0].valid_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert rates[0].valid_to == datetime(2026, 1, 2, tzinfo=timezone.utc)


@responses.activate
def test_a_gas_rate_fetch_failure_is_reported_as_a_gas_error_not_an_electricity_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        UNIT_RATES_ENDPOINT,
        body=requests.exceptions.ConnectTimeout("connection timed out"),
    )

    with pytest.raises(RuntimeError, match="gas.*connection timed out"):
        _octopus().get_gas_rates(PRODUCT_CODE, TARIFF_CODE)

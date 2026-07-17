from datetime import datetime, timezone
from decimal import Decimal

import responses
from common.config import OctopusAPISettings
from data.octopus.api import OctopusEnergyAPIClient

PRODUCT_CODE = "AGILE-24-10-01"
TARIFF_CODE = "E-1R-AGILE-24-10-01-H"
UNIT_RATES_ENDPOINT = (
    f"https://api.octopus.energy/v1/products/{PRODUCT_CODE}/electricity-tariffs/"
    f"{TARIFF_CODE}/standard-unit-rates/"
)
STANDING_CHARGES_ENDPOINT = (
    f"https://api.octopus.energy/v1/products/{PRODUCT_CODE}/electricity-tariffs/"
    f"{TARIFF_CODE}/standing-charges/"
)


def _octopus() -> OctopusEnergyAPIClient:
    return OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )


@responses.activate
def test_half_hourly_unit_rates_are_paired_with_the_standing_charge_in_effect() -> None:
    responses.add(
        responses.GET,
        UNIT_RATES_ENDPOINT,
        json={
            "results": [
                {
                    "value_inc_vat": 24.53,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-01T00:30:00Z",
                },
                {
                    "value_inc_vat": 26.10,
                    "valid_from": "2026-01-01T00:30:00Z",
                    "valid_to": "2026-01-01T01:00:00Z",
                },
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
                    "value_inc_vat": 48.20,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                }
            ],
            "next": None,
        },
        status=200,
    )

    rates = _octopus().get_electricity_rates(PRODUCT_CODE, TARIFF_CODE)

    assert len(rates) == 2
    assert rates[0].unit_rate == Decimal("24.53")
    assert rates[0].standing_charge == Decimal("48.20")
    assert rates[0].valid_from == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert rates[0].valid_to == datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    assert rates[1].unit_rate == Decimal("26.10")
    assert rates[1].standing_charge == Decimal("48.20")


@responses.activate
def test_a_unit_rate_window_with_no_covering_standing_charge_is_skipped_not_crashed() -> (
    None
):
    responses.add(
        responses.GET,
        UNIT_RATES_ENDPOINT,
        json={
            "results": [
                {
                    "value_inc_vat": 24.53,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-01T00:30:00Z",
                },
                {
                    "value_inc_vat": 26.10,
                    "valid_from": "2026-01-01T00:30:00Z",
                    "valid_to": "2026-01-01T01:00:00Z",
                },
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
                    "value_inc_vat": 48.20,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-01T00:30:00Z",
                }
            ],
            "next": None,
        },
        status=200,
    )

    rates = _octopus().get_electricity_rates(PRODUCT_CODE, TARIFF_CODE)

    assert len(rates) == 1
    assert rates[0].valid_from == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


@responses.activate
def test_paginated_unit_rates_are_followed_to_completion() -> None:
    next_page_endpoint = UNIT_RATES_ENDPOINT + "?page=2"
    responses.add(
        responses.GET,
        UNIT_RATES_ENDPOINT,
        json={
            "results": [
                {
                    "value_inc_vat": 24.53,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": "2026-01-01T00:30:00Z",
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
                    "value_inc_vat": 26.10,
                    "valid_from": "2026-01-01T00:30:00Z",
                    "valid_to": "2026-01-01T01:00:00Z",
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
                    "value_inc_vat": 48.20,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                }
            ],
            "next": None,
        },
        status=200,
    )

    rates = _octopus().get_electricity_rates(PRODUCT_CODE, TARIFF_CODE)

    assert [r.unit_rate for r in rates] == [Decimal("24.53"), Decimal("26.10")]

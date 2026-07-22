from datetime import date

import pytest
import requests
import responses
from common.config import OctopusAPISettings
from common.exceptions import APIError
from data.octopus.kraken import BillingPeriodClient, KrakenTransport
from data.octopus.model import BillingPeriod

GRAPHQL_ENDPOINT = "https://api.octopus.energy/v1/graphql/"


def _mock_token_mint() -> None:
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"data": {"obtainKrakenToken": {"token": "kraken-jwt-token"}}},
        status=200,
    )


def _mock_billing_options(start: str, end: object, is_fixed: bool) -> None:
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={
            "data": {
                "account": {
                    "billingOptions": {
                        "currentBillingPeriodStartDate": start,
                        "currentBillingPeriodEndDate": end,
                        "isFixed": is_fixed,
                    }
                }
            }
        },
        status=200,
    )


def _client() -> BillingPeriodClient:
    settings = OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    return BillingPeriodClient(settings, KrakenTransport())


@responses.activate
def test_isFixed_true_uses_the_kraken_end_date_directly() -> None:
    _mock_token_mint()
    _mock_billing_options("2026-07-06", "2026-08-05", is_fixed=True)

    billing_period = _client().get_current_billing_period()

    assert billing_period.start == date(2026, 7, 6)
    assert billing_period.end == date(2026, 8, 5)


@responses.activate
def test_isFixed_false_falls_back_to_start_plus_one_calendar_month() -> None:
    _mock_token_mint()
    _mock_billing_options("2026-07-06", None, is_fixed=False)

    billing_period = _client().get_current_billing_period()

    assert billing_period.start == date(2026, 7, 6)
    assert billing_period.end == date(2026, 8, 6)


@responses.activate
def test_isFixed_false_clamps_to_the_last_valid_day_of_a_shorter_month() -> None:
    _mock_token_mint()
    _mock_billing_options("2026-01-31", None, is_fixed=False)

    billing_period = _client().get_current_billing_period()

    assert billing_period.start == date(2026, 1, 31)
    assert billing_period.end == date(2026, 2, 28)


@responses.activate
def test_isFixed_false_clamps_correctly_across_a_leap_year_february() -> None:
    _mock_token_mint()
    _mock_billing_options("2028-01-31", None, is_fixed=False)

    billing_period = _client().get_current_billing_period()

    assert billing_period.end == date(2028, 2, 29)


@responses.activate
def test_isFixed_false_rolls_over_a_year_boundary() -> None:
    _mock_token_mint()
    _mock_billing_options("2026-12-15", None, is_fixed=False)

    billing_period = _client().get_current_billing_period()

    assert billing_period.end == date(2027, 1, 15)


@responses.activate
def test_token_mint_failure_raises_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"errors": [{"message": "Invalid API key"}]},
        status=200,
    )

    with pytest.raises(APIError, match="Invalid API key"):
        _client().get_current_billing_period()


@responses.activate
def test_billing_options_query_failure_raises_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    _mock_token_mint()
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        json={"detail": "server error"},
        status=500,
    )

    with pytest.raises(APIError, match="server error"):
        _client().get_current_billing_period()


@responses.activate
def test_connection_failure_raises_a_descriptive_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.POST,
        GRAPHQL_ENDPOINT,
        body=requests.exceptions.ConnectTimeout("connection timed out"),
    )

    with pytest.raises(RuntimeError, match="mint Kraken token.*connection timed out"):
        _client().get_current_billing_period()


@responses.activate
def test_every_call_re_authenticates_rather_than_reusing_a_cached_token() -> None:
    _mock_token_mint()
    _mock_billing_options("2026-07-06", "2026-08-05", is_fixed=True)
    _mock_token_mint()
    _mock_billing_options("2026-08-06", "2026-09-05", is_fixed=True)
    client = _client()

    client.get_current_billing_period()
    client.get_current_billing_period()

    token_mint_calls = [
        call
        for call in responses.calls
        if "obtainKrakenToken" in call.request.body.decode()
    ]
    assert len(token_mint_calls) == 2


def test_isFixed_true_with_no_end_date_raises_rather_than_silently_falling_back() -> (
    None
):
    # isFixed: true with a null end date contradicts Kraken's own schema
    # ("Null if the account is on flexible billing") -- a genuine contract
    # violation, not the expected flexible-billing case. Falling through to
    # the flexible-billing month-clamp math here would fabricate a plausible
    # -looking date instead of surfacing the anomaly.
    with pytest.raises(ValueError, match="isFixed.*true"):
        BillingPeriod.from_billing_options(date(2026, 7, 6), None, is_fixed=True)

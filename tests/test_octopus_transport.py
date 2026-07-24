from typing import Any, List

import pytest
import requests
import responses
from common.config import OctopusAPISettings
from common.exceptions import APIError
from data.octopus.transport import OctopusTransport
from pydantic import BaseModel

ENDPOINT = "https://api.octopus.energy/v1/widgets/"


class _WidgetResponse(BaseModel):
    name: str


@responses.activate
def test_get_returns_the_validated_response_model() -> None:
    responses.add(responses.GET, ENDPOINT, json={"name": "gadget"}, status=200)
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    result = transport.get(ENDPOINT, _WidgetResponse)

    assert result.name == "gadget"


@responses.activate
def test_get_reuses_the_same_session_across_multiple_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A historical backfill makes hundreds of sequential paginated requests
    # to the same host -- each call should resolve DNS and open a connection
    # once, not per request, so a burst is served by one requests.Session
    # rather than a fresh one every time.
    responses.add(responses.GET, ENDPOINT, json={"name": "gadget"}, status=200)
    responses.add(responses.GET, ENDPOINT, json={"name": "gadget"}, status=200)
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    serving_sessions: List[requests.Session] = []
    original_get = requests.Session.get

    def spy_get(self: requests.Session, *args: Any, **kwargs: Any) -> requests.Response:
        serving_sessions.append(self)
        return original_get(self, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "get", spy_get)

    transport.get(ENDPOINT, _WidgetResponse)
    transport.get(ENDPOINT, _WidgetResponse)

    assert len(serving_sessions) == 2
    assert serving_sessions[0] is serving_sessions[1]


@responses.activate
def test_get_raises_api_error_with_json_body_on_non_200_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(responses.GET, ENDPOINT, json={"detail": "not found"}, status=404)
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(APIError, match="not found"):
        transport.get(ENDPOINT, _WidgetResponse)


@responses.activate
def test_get_raises_api_error_with_text_body_on_non_json_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ENDPOINT,
        body="Internal Server Error",
        status=500,
        content_type="text/plain",
    )
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(APIError, match="Internal Server Error"):
        transport.get(ENDPOINT, _WidgetResponse)


@responses.activate
def test_get_raises_a_descriptive_runtime_error_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ENDPOINT,
        body=requests.exceptions.ConnectTimeout("connection timed out"),
    )
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(RuntimeError, match="fetch widgets.*connection timed out"):
        transport.get(ENDPOINT, _WidgetResponse, description="fetch widgets")


@responses.activate
def test_get_succeeds_after_a_transient_connection_failure_via_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test: a reused, potentially stale pooled connection must not
    # break the existing @retry() path -- urllib3's connection pool evicts a
    # dead pooled connection and opens a fresh one on the retried call.
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(
        responses.GET,
        ENDPOINT,
        body=requests.exceptions.ConnectionError("connection reset"),
    )
    responses.add(responses.GET, ENDPOINT, json={"name": "gadget"}, status=200)
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    result = transport.get(ENDPOINT, _WidgetResponse)

    assert result.name == "gadget"


@responses.activate
def test_get_raises_a_descriptive_runtime_error_on_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    responses.add(responses.GET, ENDPOINT, json={}, status=200)
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(RuntimeError) as exc_info:
        transport.get(ENDPOINT, _WidgetResponse, description="fetch widgets")

    assert "fetch widgets" in str(exc_info.value)
    assert "name" in str(exc_info.value)
    assert "field required" in str(exc_info.value).lower()

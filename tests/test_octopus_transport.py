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

from datetime import datetime, timezone

from common.config import OctopusAPISettings
from data.octopus.consumption import ConsumptionClient
from data.octopus.transport import OctopusTransport


def _client() -> ConsumptionClient:
    transport = OctopusTransport(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )
    return ConsumptionClient(transport)


def test_period_from_and_period_to_are_both_encoded_as_distinct_query_params() -> None:
    endpoint = _client().build_api_endpoint_from_params(
        "https://api.octopus.energy/v1/consumption/",
        period_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_to=datetime(2026, 1, 2, tzinfo=timezone.utc),
        page_size=100,
    )

    assert "period_from=2026-01-01T00:00:00Z" in endpoint
    assert "period_to=2026-01-02T00:00:00Z" in endpoint
    assert endpoint.count("period_from=") == 1
    assert endpoint.count("period_to=") == 1

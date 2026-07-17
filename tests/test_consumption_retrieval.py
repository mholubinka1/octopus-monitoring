from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pytest
import responses
from common.config import OctopusAPISettings
from data.consumption import ConsumptionRetriever
from data.model import Consumption, Energy
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Agreement, Electricity, Meter

CONSUMPTION_ENDPOINT = (
    "https://api.octopus.energy/v1/electricity-meter-points/"
    "1234567890123/meters/00A1234567/consumption/"
)


class _RealConsumptionSource:
    """A real ConsumptionSource adapter for tests: genuine OctopusEnergyAPIClient
    and MariaDBClient underneath, with meters fixed up front rather than
    fetched, so tests only need to mock the consumption HTTP endpoints
    ConsumptionRetriever actually calls."""

    def __init__(
        self,
        octopus: OctopusEnergyAPIClient,
        mariadb: MariaDBClient,
        meters: List[Meter],
    ) -> None:
        self._octopus = octopus
        self._mariadb = mariadb
        self.meters = meters

    def refresh_meters(self) -> None:
        pass

    def fetch_consumption(
        self, meter: Meter, period_from: datetime
    ) -> Tuple[Optional[str], List[Consumption]]:
        return self._octopus.get_consumption(meter, period_from)

    def fetch_consumption_page(
        self, energy: Energy, next_page: str
    ) -> Tuple[Optional[str], List[Consumption]]:
        return self._octopus.get_consumption_directly_from_endpoint(energy, next_page)

    def persist_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        self._mariadb.write_consumption(meter, consumption)


def _make_meter() -> Electricity:
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


@responses.activate
def test_refresh_resumes_from_the_true_max_across_all_pages_not_just_the_last(
    monkeypatch: pytest.MonkeyPatch,
    mariadb_client: MariaDBClient,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    next_page_url = CONSUMPTION_ENDPOINT + "?page=2"

    # First fetch (explicit period_from=2026-01-01): page 1 has a reading
    # ending 2026-01-02, and points to a second, empty page.
    responses.add(
        responses.GET,
        CONSUMPTION_ENDPOINT
        + "?page_size=100&period_from=2026-01-01T00:00:00Z&order_by=period",
        json={
            "results": [
                {
                    "consumption": "1.0",
                    "interval_start": "2026-01-02T00:00:00+00:00",
                    "interval_end": "2026-01-02T00:00:00+00:00",
                }
            ],
            "next": next_page_url,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        next_page_url,
        json={"results": [], "next": None},
        status=200,
    )
    # refresh() resumes from page 1's true max (2026-01-02), not the empty
    # final page's date — this is the exact bug this test pins down.
    responses.add(
        responses.GET,
        CONSUMPTION_ENDPOINT
        + "?page_size=100&period_from=2026-01-02T00:00:00Z&order_by=period",
        json={"results": [], "next": None},
        status=200,
    )

    meter = _make_meter()
    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )
    source = _RealConsumptionSource(octopus, mariadb_client, [meter])
    retriever = ConsumptionRetriever(source)

    retriever.get_meter_consumption(
        meter, period_from=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    retriever.refresh()

    # The empty final page must not overwrite the resume point with a crash or
    # a stale date — refresh() should resume from page 1's true latest date.
    # If it resumed from the wrong date, the registered response above
    # wouldn't match and responses would raise a ConnectionError instead.
    resume_request_urls = [call.request.url for call in responses.calls]
    assert any("period_from=2026-01-02T00" in url for url in resume_request_urls[2:])

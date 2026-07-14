from datetime import datetime, timezone
from decimal import Decimal

import pytest
import responses
from common.config import OctopusAPISettings
from common.exceptions import APIError
from data.model import Energy
from data.mysql import sql_models
from data.mysql.client import MariaDBClient
from data.octopus.api import OctopusEnergyAPIClient
from data.octopus.model import Agreement, Electricity

CONSUMPTION_ENDPOINT = (
    "https://api.octopus.energy/v1/electricity-meter-points/"
    "1234567890123/meters/00A1234567/consumption/"
)


@responses.activate
def test_consumption_fetched_from_octopus_is_persisted_and_queryable(
    mariadb_client: MariaDBClient,
) -> None:
    responses.add(
        responses.GET,
        CONSUMPTION_ENDPOINT,
        json={
            "results": [
                {
                    "consumption": "1.234",
                    "interval_start": "2026-01-01T00:00:00+00:00",
                    "interval_end": "2026-01-01T00:30:00+00:00",
                }
            ],
            "next": None,
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )
    meter = Electricity(
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

    _, consumption = octopus.get_consumption_directly_from_endpoint(
        Energy.electricity, CONSUMPTION_ENDPOINT
    )

    mariadb_client.write_consumption(meter, consumption)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(sql_models.consumption).all()

    assert len(stored) == 1
    assert stored[0].id == "E20260101000000"
    assert Decimal(str(stored[0].est_kwh)) == Decimal("1.234")


@responses.activate
def test_consumption_response_missing_a_required_field_raises_a_clear_validation_error() -> (
    None
):
    responses.add(
        responses.GET,
        CONSUMPTION_ENDPOINT,
        json={
            "results": [
                {
                    "interval_start": "2026-01-01T00:00:00+00:00",
                    "interval_end": "2026-01-01T00:30:00+00:00",
                }
            ],
            "next": None,
        },
        status=200,
    )

    octopus = OctopusEnergyAPIClient(
        OctopusAPISettings(account_number="A-1234ABCD", api_key="sk_live_test")
    )

    with pytest.raises(APIError) as exc_info:
        octopus.get_consumption_directly_from_endpoint(
            Energy.electricity, CONSUMPTION_ENDPOINT
        )

    assert "consumption" in str(exc_info.value)
    assert "field required" in str(exc_info.value).lower()

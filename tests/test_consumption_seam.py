from datetime import UTC, datetime
from decimal import Decimal

import pytest
import responses
from common.config import OctopusAPISettings
from data.model import Energy
from data.mysql import model
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
                valid_from=datetime(2022, 11, 1, tzinfo=UTC),
                valid_to=None,
            )
        ],
    )

    _, consumption = octopus.get_consumption_directly_from_endpoint(
        Energy.electricity, CONSUMPTION_ENDPOINT
    )

    mariadb_client.write_consumption(meter, consumption)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.consumption).all()

    assert len(stored) == 1
    assert stored[0].id == "E20260101000000"
    assert stored[0].est_kwh == Decimal("1.234")


@responses.activate
def test_a_bst_offset_consumption_reading_is_persisted_at_its_correct_utc_instant(
    mariadb_client: MariaDBClient,
) -> None:
    # Octopus's consumption endpoint returns interval_start/interval_end in
    # local British time -- 2026-07-01T01:00:00+01:00 (BST) is the true UTC
    # instant 2026-07-01T00:00:00. Storage must reflect the latter, not the
    # local wall-clock digits with the offset silently dropped.
    responses.add(
        responses.GET,
        CONSUMPTION_ENDPOINT,
        json={
            "results": [
                {
                    "consumption": "0.5",
                    "interval_start": "2026-07-01T01:00:00+01:00",
                    "interval_end": "2026-07-01T01:30:00+01:00",
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
                valid_from=datetime(2022, 11, 1, tzinfo=UTC),
                valid_to=None,
            )
        ],
    )

    _, consumption = octopus.get_consumption_directly_from_endpoint(
        Energy.electricity, CONSUMPTION_ENDPOINT
    )

    mariadb_client.write_consumption(meter, consumption)

    with mariadb_client.session_read_scope() as session:
        stored = session.query(model.consumption).all()

    assert len(stored) == 1
    assert stored[0].id == "E20260701000000"
    assert stored[0].period_from == datetime(2026, 7, 1, 0, 0, tzinfo=UTC).replace(
        tzinfo=None
    )
    assert stored[0].period_to == datetime(2026, 7, 1, 0, 30, tzinfo=UTC).replace(
        tzinfo=None
    )


@responses.activate
def test_consumption_response_missing_a_required_field_raises_a_clear_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
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

    with pytest.raises(RuntimeError) as exc_info:
        octopus.get_consumption_directly_from_endpoint(
            Energy.electricity, CONSUMPTION_ENDPOINT
        )

    assert "consumption" in str(exc_info.value)
    assert "field required" in str(exc_info.value).lower()

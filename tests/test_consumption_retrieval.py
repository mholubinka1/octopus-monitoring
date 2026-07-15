from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from data.consumption import ConsumptionRetriever
from data.model import Consumption, Unit
from data.octopus.model import Agreement, Electricity


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


def _make_reading(end: datetime) -> Consumption:
    return Consumption(
        raw=Decimal("1.0"),
        est_kwh=Decimal("1.0"),
        unit=Unit.kwh,
        start=end,
        end=end,
    )


def test_refresh_resumes_from_the_true_max_across_all_pages_not_just_the_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("common.decorator.time.sleep", lambda seconds: None)
    meter = _make_meter()
    page_1_reading = _make_reading(datetime(2026, 1, 2, tzinfo=timezone.utc))

    client = Mock()
    client.meters = [meter]
    client.octopus.get_consumption.return_value = ("next-page-url", [page_1_reading])
    client.octopus.get_consumption_directly_from_endpoint.return_value = (None, [])

    retriever = ConsumptionRetriever(client)
    retriever.get_meter_consumption(
        meter, period_from=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert client.mariadb.write_consumption.call_count == 1

    retriever.refresh()

    # The empty final page must not overwrite the resume point with a crash or
    # a stale date — refresh() should resume from page 1's true latest date.
    second_call_period_from = client.octopus.get_consumption.call_args_list[1].args[1]
    assert second_call_period_from == datetime(2026, 1, 2, tzinfo=timezone.utc)

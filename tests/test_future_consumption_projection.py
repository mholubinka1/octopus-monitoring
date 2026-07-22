from decimal import Decimal

import pytest
from data.cost_forecast import project_daily_average_consumption


def test_projects_the_average_of_the_elapsed_daily_totals() -> None:
    result = project_daily_average_consumption(
        [Decimal("10.0"), Decimal("12.0"), Decimal("8.0")]
    )

    assert result == Decimal("10")


def test_a_single_elapsed_day_projects_that_days_total() -> None:
    result = project_daily_average_consumption([Decimal("7.5")])

    assert result == Decimal("7.5")


def test_zero_consumption_days_are_included_in_the_average() -> None:
    result = project_daily_average_consumption(
        [Decimal("0"), Decimal("0"), Decimal("12.0")]
    )

    assert result == Decimal("4")


def test_no_elapsed_days_raises_a_clear_error() -> None:
    with pytest.raises(ValueError, match="[Nn]o elapsed"):
        project_daily_average_consumption([])

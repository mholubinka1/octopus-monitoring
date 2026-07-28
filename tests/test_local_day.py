from datetime import UTC, date, datetime

from data.local_day import expected_half_hour_count, start_of_local_day, to_local_date


def test_a_late_evening_bst_instant_before_utc_midnight_falls_on_the_next_local_day() -> (
    None
):
    # 2026-07-20 23:30 UTC is 2026-07-21 00:30 in Europe/London during BST --
    # the local day has already turned over even though the UTC day hasn't.
    instant = datetime(2026, 7, 20, 23, 30, tzinfo=UTC)

    assert to_local_date(instant) == date(2026, 7, 21)


def test_a_naive_instant_from_a_database_row_is_treated_as_utc() -> None:
    # consumption.period_from comes back from MariaDB/SQLite as a naive
    # datetime representing a UTC instant -- the same BST-crossing instant
    # as above, but without tzinfo attached.
    instant = datetime(2026, 7, 20, 23, 30)  # noqa: DTZ001 -- naive is the point

    assert to_local_date(instant) == date(2026, 7, 21)


def test_an_ordinary_day_has_forty_eight_expected_half_hour_slots() -> None:
    assert expected_half_hour_count(date(2026, 7, 20)) == 48


def test_the_uk_spring_forward_date_has_forty_six_expected_half_hour_slots() -> None:
    # 2026-03-29 is the last Sunday in March -- clocks go forward 01:00 to
    # 02:00 UK time, so the local day is only 23 hours long.
    assert expected_half_hour_count(date(2026, 3, 29)) == 46


def test_the_uk_fall_back_date_has_fifty_expected_half_hour_slots() -> None:
    # 2026-10-25 is the last Sunday in October -- clocks go back 02:00 to
    # 01:00 UK time, so the local day is 25 hours long.
    assert expected_half_hour_count(date(2026, 10, 25)) == 50


def test_days_either_side_of_a_clock_change_are_still_ordinary_forty_eight_slot_days() -> (
    None
):
    assert expected_half_hour_count(date(2026, 3, 28)) == 48
    assert expected_half_hour_count(date(2026, 3, 30)) == 48
    assert expected_half_hour_count(date(2026, 10, 24)) == 48
    assert expected_half_hour_count(date(2026, 10, 26)) == 48


def test_the_start_of_a_bst_local_day_is_one_hour_before_utc_midnight() -> None:
    # Local midnight on 2026-07-06 (BST, UTC+1) is UTC 2026-07-05 23:00.
    assert start_of_local_day(date(2026, 7, 6)) == datetime(
        2026, 7, 5, 23, 0, tzinfo=UTC
    )


def test_the_start_of_a_gmt_local_day_is_utc_midnight() -> None:
    # Outside BST (GMT, UTC+0), local midnight is UTC midnight.
    assert start_of_local_day(date(2026, 1, 6)) == datetime(
        2026, 1, 6, 0, 0, tzinfo=UTC
    )

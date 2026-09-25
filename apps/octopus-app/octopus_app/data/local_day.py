from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
HALF_HOUR = timedelta(minutes=30)


def to_local_date(instant: datetime) -> date:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(LONDON).date()


def start_of_local_day(local_date: date) -> datetime:
    return datetime(
        local_date.year, local_date.month, local_date.day, tzinfo=LONDON
    ).astimezone(UTC)


def expected_half_hour_count(local_date: date) -> int:
    start_of_day = start_of_local_day(local_date)
    start_of_next_day = start_of_local_day(local_date + timedelta(days=1))
    duration = start_of_next_day - start_of_day
    return duration // HALF_HOUR

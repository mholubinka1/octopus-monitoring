from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
HALF_HOUR = timedelta(minutes=30)


def to_local_date(instant: datetime) -> date:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(LONDON).date()


def expected_half_hour_count(local_date: date) -> int:
    start_of_day = datetime(
        local_date.year, local_date.month, local_date.day, tzinfo=LONDON
    )
    start_of_next_day = start_of_day + timedelta(days=1)
    duration = start_of_next_day.astimezone(UTC) - start_of_day.astimezone(UTC)
    return duration // HALF_HOUR

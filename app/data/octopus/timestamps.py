from datetime import datetime, timezone

from common.exceptions import ArgumentError


def to_utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        # A naive datetime would silently pick up the system's local tz via
        # astimezone(), reintroducing the exact offset bug this
        # normalization exists to fix — fail fast instead.
        raise ArgumentError(
            f"period_from/period_to must be timezone-aware, got naive "
            f"datetime {value!r}."
        )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

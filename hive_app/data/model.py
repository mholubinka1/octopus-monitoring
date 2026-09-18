from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class HeatingStatus:
    polled_at: datetime
    current_temp: float
    target_temp: float
    mode: str
    state: str
    boost_active: bool
    boost_ends_at: datetime | None
    schedule: dict[str, Any]


@dataclass
class HiveAuthState:
    refresh_token: str
    device_group_key: str
    device_key: str
    updated_at: datetime

from datetime import UTC, datetime

import requests
from pydantic import BaseModel

from hive_app.common.config import LocationSettings
from hive_app.data.model import WeatherObservation
from hive_app.data.weather_types import REQUEST_TIMEOUT_SECONDS, FiniteFloat

CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,surface_pressure,"
    "wind_speed_10m,precipitation"
)


class OpenMeteoCurrent(BaseModel):
    time: datetime
    temperature_2m: FiniteFloat
    relative_humidity_2m: FiniteFloat
    surface_pressure: FiniteFloat
    wind_speed_10m: FiniteFloat
    precipitation: FiniteFloat


class OpenMeteoResponse(BaseModel):
    current: OpenMeteoCurrent


class OpenMeteoClient:
    base_url: str = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, settings: LocationSettings) -> None:
        self._settings = settings

    def get_current_observation(self) -> WeatherObservation:
        response = requests.get(
            url=self.base_url,
            params={
                "latitude": str(self._settings.latitude),
                "longitude": str(self._settings.longitude),
                "current": CURRENT_FIELDS,
                # Open-Meteo defaults "current.time" to the location's local
                # timezone (or GMT) when none is requested -- forcing UTC
                # here means the naive timestamp it returns can be treated
                # as UTC below without guessing an offset.
                "timezone": "UTC",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        parsed = OpenMeteoResponse.model_validate(response.json())
        current = parsed.current

        return WeatherObservation(
            source="open-meteo",
            observed_at=current.time.replace(tzinfo=UTC),
            temp=current.temperature_2m,
            humidity=current.relative_humidity_2m,
            pressure=current.surface_pressure,
            wind_speed=current.wind_speed_10m,
            precipitation=current.precipitation,
        )

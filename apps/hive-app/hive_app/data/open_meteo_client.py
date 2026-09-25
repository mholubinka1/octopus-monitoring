from datetime import UTC, date, datetime
from typing import Any

import requests
from pydantic import BaseModel

from hive_app.common.config import LocationSettings
from hive_app.data.model import WeatherForecastDay, WeatherObservation
from hive_app.data.weather_types import REQUEST_TIMEOUT_SECONDS, FiniteFloat

CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,surface_pressure,"
    "wind_speed_10m,precipitation"
)
DAILY_FIELDS = "temperature_2m_max"


class OpenMeteoCurrent(BaseModel):
    time: datetime
    temperature_2m: FiniteFloat
    relative_humidity_2m: FiniteFloat
    surface_pressure: FiniteFloat
    wind_speed_10m: FiniteFloat
    precipitation: FiniteFloat


class OpenMeteoResponse(BaseModel):
    current: OpenMeteoCurrent


class OpenMeteoDaily(BaseModel):
    time: list[date]
    temperature_2m_max: list[FiniteFloat]


class OpenMeteoForecastResponse(BaseModel):
    daily: OpenMeteoDaily


class OpenMeteoClient:
    base_url: str = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, settings: LocationSettings) -> None:
        self._settings = settings

    def _request(self, endpoint_params: dict[str, str]) -> dict[str, Any]:
        # Shared by every Open-Meteo endpoint this client calls: latitude,
        # longitude and a forced UTC timezone are common to both the
        # current-observation and forecast requests -- forcing UTC means
        # the naive timestamps/dates Open-Meteo returns can be treated as
        # UTC by the caller without guessing an offset.
        response = requests.get(
            url=self.base_url,
            params={
                "latitude": str(self._settings.latitude),
                "longitude": str(self._settings.longitude),
                "timezone": "UTC",
                **endpoint_params,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def get_current_observation(self) -> WeatherObservation:
        payload = self._request({"current": CURRENT_FIELDS})
        parsed = OpenMeteoResponse.model_validate(payload)
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

    def get_forecast(self) -> list[WeatherForecastDay]:
        payload = self._request({"daily": DAILY_FIELDS})
        parsed = OpenMeteoForecastResponse.model_validate(payload)
        daily = parsed.daily

        if len(daily.time) != len(daily.temperature_2m_max):
            raise ValueError(
                "Open-Meteo forecast response has mismatched array lengths: "
                f"{len(daily.time)} time entries vs "
                f"{len(daily.temperature_2m_max)} temperature_2m_max entries."
            )

        fetched_at = datetime.now(UTC)
        return [
            WeatherForecastDay(
                source="open-meteo",
                target_date=target_date,
                max_temp=max_temp,
                fetched_at=fetched_at,
            )
            for target_date, max_temp in zip(daily.time, daily.temperature_2m_max)
        ]

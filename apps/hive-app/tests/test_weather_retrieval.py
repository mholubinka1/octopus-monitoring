from datetime import UTC, datetime

import pytest

from hive_app.data.model import WeatherForecastDay, WeatherObservation
from hive_app.data.weather import WeatherRetriever


def _observation(source: str) -> WeatherObservation:
    return WeatherObservation(
        source=source,
        observed_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        temp=14.5,
        humidity=72,
        pressure=1012.3,
        wind_speed=8.1,
        precipitation=0.0,
    )


class _FakeWeatherSourceFallsBackToOpenMeteo:
    """A fake WeatherSource whose primary (Weather Underground) fetch raises
    and whose fallback (Open-Meteo) fetch succeeds -- proves WeatherRetriever
    persists the fallback's observation, mirroring
    AgileForecastRetriever.refresh()'s primary/fallback shape."""

    def __init__(self) -> None:
        self.persisted: WeatherObservation | None = None

    def fetch_current_observation(self) -> WeatherObservation:
        raise ConnectionError("api.weather.com unreachable")

    def fetch_current_observation_fallback(self) -> WeatherObservation:
        return _observation("open-meteo")

    def persist_current_observation(self, observation: WeatherObservation) -> None:
        self.persisted = observation

    def fetch_forecast(self) -> list[WeatherForecastDay]:
        raise NotImplementedError

    def persist_forecast(self, forecast: list[WeatherForecastDay]) -> None:
        raise NotImplementedError


def test_refresh_falls_back_to_open_meteo_when_wunderground_fetch_fails() -> None:
    source = _FakeWeatherSourceFallsBackToOpenMeteo()

    WeatherRetriever(source).refresh()

    assert source.persisted is not None
    assert source.persisted.source == "open-meteo"


class _FakeWeatherSourceBothFail:
    """A fake WeatherSource whose primary and fallback fetches both raise --
    proves WeatherRetriever.refresh() does no retry/backoff/swallowing of its
    own (that's the generic job-wrapper's job); it just propagates."""

    def fetch_current_observation(self) -> WeatherObservation:
        raise ConnectionError("api.weather.com unreachable")

    def fetch_current_observation_fallback(self) -> WeatherObservation:
        raise ConnectionError("api.open-meteo.com unreachable")

    def persist_current_observation(self, observation: WeatherObservation) -> None:
        raise AssertionError("persist_current_observation should never be reached")

    def fetch_forecast(self) -> list[WeatherForecastDay]:
        raise NotImplementedError

    def persist_forecast(self, forecast: list[WeatherForecastDay]) -> None:
        raise NotImplementedError


def test_refresh_propagates_when_both_wunderground_and_open_meteo_fail() -> None:
    source = _FakeWeatherSourceBothFail()

    with pytest.raises(ConnectionError, match="api.open-meteo.com unreachable"):
        WeatherRetriever(source).refresh()


class _FakeWeatherSourceForecastFails:
    """A fake WeatherSource whose forecast fetch raises -- proves
    WeatherRetriever.refresh_forecast() has no fallback and no try/except
    of its own (AC2: no fallback source attempted), just propagates
    straight to the generic job wrapper."""

    def fetch_current_observation(self) -> WeatherObservation:
        raise NotImplementedError

    def fetch_current_observation_fallback(self) -> WeatherObservation:
        raise NotImplementedError

    def persist_current_observation(self, observation: WeatherObservation) -> None:
        raise NotImplementedError

    def fetch_forecast(self) -> list[WeatherForecastDay]:
        raise ConnectionError("api.open-meteo.com unreachable")

    def persist_forecast(self, forecast: list[WeatherForecastDay]) -> None:
        raise AssertionError("persist_forecast should never be reached")


def test_refresh_forecast_propagates_when_the_forecast_fetch_fails() -> None:
    source = _FakeWeatherSourceForecastFails()

    with pytest.raises(ConnectionError, match="api.open-meteo.com unreachable"):
        WeatherRetriever(source).refresh_forecast()

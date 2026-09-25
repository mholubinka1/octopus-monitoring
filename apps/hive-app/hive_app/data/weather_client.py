from hive_app.common.config import LocationSettings, WeatherUndergroundSettings
from hive_app.data.model import WeatherObservation
from hive_app.data.mysql.client import MariaDBClient
from hive_app.data.open_meteo_client import OpenMeteoClient
from hive_app.data.weather_underground_client import WeatherUndergroundClient


class WeatherApiSource:
    _wunderground: WeatherUndergroundClient
    _open_meteo: OpenMeteoClient
    _mariadb: MariaDBClient

    def __init__(
        self,
        wunderground: WeatherUndergroundSettings,
        location: LocationSettings,
        mariadb: MariaDBClient,
    ) -> None:
        self._wunderground = WeatherUndergroundClient(wunderground)
        self._open_meteo = OpenMeteoClient(location)
        self._mariadb = mariadb

    def fetch_current_observation(self) -> WeatherObservation:
        return self._wunderground.get_current_observation()

    def fetch_current_observation_fallback(self) -> WeatherObservation:
        return self._open_meteo.get_current_observation()

    def persist_current_observation(self, observation: WeatherObservation) -> None:
        self._mariadb.write_weather_observation(observation)

import logging.config
from datetime import date
from logging import Logger, getLogger

from common.config import MariaDBSettings
from common.mariadb.client import MariaDBClientBase
from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus, WeatherForecastDay, WeatherObservation
from hive_app.data.mysql import model as sql_model
from hive_app.data.mysql.model import SQLBase

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def _forecast_scoped_id(source: str, target_date: date) -> str:
    return f"{source}_{target_date.strftime('%Y%m%d')}"


class MariaDBClient(MariaDBClientBase):
    def __init__(self, settings: MariaDBSettings) -> None:
        super().__init__(settings, declarative_base=SQLBase, logger=logger)

    def write_heating_status(self, status: HeatingStatus) -> None:
        # sqlalchemy-stubs models every Numeric subclass (Float included) as
        # TypeEngine[Decimal], so it reports a float/Decimal mismatch here even
        # though SQLAlchemy's real runtime Float column stores/returns a plain
        # Python float -- a known stub-accuracy gap, not a real type error.
        record = sql_model.heating_status(
            polled_at=status.polled_at,
            current_temp=status.current_temp,  # type: ignore[misc]
            target_temp=status.target_temp,  # type: ignore[misc]
            mode=status.mode,
            state=status.state,
            boost_active=status.boost_active,
            boost_ends_at=status.boost_ends_at,
            schedule=status.schedule,
        )
        self._write_all([record], "Heating status data")

    def write_weather_observation(self, observation: WeatherObservation) -> None:
        # sqlalchemy-stubs models every Numeric subclass (Float included) as
        # TypeEngine[Decimal], so it reports a float/Decimal mismatch here even
        # though SQLAlchemy's real runtime Float column stores/returns a plain
        # Python float -- a known stub-accuracy gap, not a real type error.
        record = sql_model.weather_observation(
            source=observation.source,
            observed_at=observation.observed_at,
            temp=observation.temp,  # type: ignore[misc]
            humidity=observation.humidity,  # type: ignore[misc]
            pressure=observation.pressure,  # type: ignore[misc]
            wind_speed=observation.wind_speed,  # type: ignore[misc]
            precipitation=observation.precipitation,  # type: ignore[misc]
        )
        self._write_all([record], "Weather observation data")

    def write_weather_forecast(self, forecast: list[WeatherForecastDay]) -> None:
        # sqlalchemy-stubs models every Numeric subclass (Float included) as
        # TypeEngine[Decimal], so it reports a float/Decimal mismatch here even
        # though SQLAlchemy's real runtime Float column stores/returns a plain
        # Python float -- a known stub-accuracy gap, not a real type error.
        records = [
            sql_model.weather_forecast(
                id=_forecast_scoped_id(day.source, day.target_date),
                source=day.source,
                target_date=day.target_date,
                max_temp=day.max_temp,  # type: ignore[misc]
                fetched_at=day.fetched_at,
            )
            for day in forecast
        ]
        self._write_all(records, "Weather forecast data")

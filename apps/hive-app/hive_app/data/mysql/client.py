import logging.config
from logging import Logger, getLogger

from hive_app.common.logging import APP_LOGGER_NAME, config
from hive_app.data.model import HeatingStatus
from hive_app.data.mysql import model as sql_model
from hive_app.data.mysql.model import SQLBase

from libs.common.common.config import MariaDBSettings
from libs.common.common.mariadb.client import MariaDBClientBase

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


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

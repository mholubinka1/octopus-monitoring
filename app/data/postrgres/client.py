from typing import List

from common.config import PostgresSettings
from data.model import Consumption
from data.octopus.model import Meter


class PostgresClient:
    def __init__(self, settings: PostgresSettings) -> None:
        pass

    def write_consumption(self, meter: Meter, consumption: List[Consumption]) -> None:
        pass

from datetime import datetime
from typing import Dict, List

from data.base import MonitoringClient


class PricingRetriever:
    _client: MonitoringClient

    _tariffs: List[str]
    _latest_prices: Dict[str, datetime]

    def __init__(self, client: MonitoringClient) -> None:
        self._client = client

    def retrieve_price_history(self) -> None:
        pass

    def update_price_history(self, _latest_prices: Dict[str, datetime]) -> None:
        # now = datetime.now(dt.UTC)
        pass

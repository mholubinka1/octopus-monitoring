from data.base import MonitoringClient


class PricingRetriever:
    _client: MonitoringClient

    def __init__(self, client: MonitoringClient) -> None:
        self._client = client

    def refresh(self) -> None:
        self._client.refresh_meters()
        for meter in self._client.meters:
            self._client.mariadb.write_agreement(meter, meter.agreements)

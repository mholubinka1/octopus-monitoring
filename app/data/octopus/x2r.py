from datetime import datetime, timedelta
from decimal import Decimal

import requests
from common.decorator import retry
from common.exceptions import APIError
from common.http import raise_for_http_error
from data.octopus.model import AgileForecastReading
from pydantic import BaseModel

REQUEST_TIMEOUT_SECONDS = 30
HALF_HOUR = timedelta(minutes=30)


class X2rPriceEntry(BaseModel):
    date: datetime
    price: Decimal


class X2rPrices(BaseModel):
    forecast: list[X2rPriceEntry]
    day_ahead: list[X2rPriceEntry]
    actual: list[X2rPriceEntry]


class X2rResponse(BaseModel):
    forecast_at: datetime
    region: str
    region_name: str
    prices: X2rPrices


class X2rClient:
    base_url: str = "https://api.x2r.uk/agile/"

    @retry()
    def get_forecast(self, region: str) -> list[AgileForecastReading]:
        url = self.base_url + region
        response: requests.Response | None = None
        try:
            response = requests.get(url=url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            parsed = X2rResponse.model_validate(response.json())
        except Exception as e:
            raise_for_http_error(response, e, "fetch Agile forecast")

        if not parsed.prices.forecast:
            raise APIError(f"No Agile forecast data returned for region {region}.")

        return [
            AgileForecastReading(
                period_from=entry.date,
                period_to=entry.date + HALF_HOUR,
                unit_rate=entry.price,
            )
            for entry in parsed.prices.forecast
        ]

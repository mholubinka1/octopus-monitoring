from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

import requests
from common.decorator import retry
from common.exceptions import APIError
from data.octopus.model import AgileForecastReading
from pydantic import BaseModel, RootModel

REQUEST_TIMEOUT_SECONDS = 30
HALF_HOUR = timedelta(minutes=30)


class AgilePredictPriceEntry(BaseModel):
    date_time: datetime
    agile_pred: Decimal


class AgilePredictRegionForecast(BaseModel):
    prices: List[AgilePredictPriceEntry]


class AgilePredictResponse(RootModel[List[AgilePredictRegionForecast]]):
    pass


class AgilePredictClient:
    base_url: str = "https://agilepredict.com/api/"

    @retry()
    def get_forecast(self, region: str) -> List[AgileForecastReading]:
        url = self.base_url + f"{region}/"
        response: Optional[requests.Response] = None
        try:
            response = requests.get(url=url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            parsed = AgilePredictResponse.model_validate(response.json())
        except Exception as e:
            if response is not None and response.status_code != 200:
                try:
                    error_body: object = response.json()
                except ValueError:
                    error_body = response.text
                raise APIError(error_body) from e
            raise RuntimeError(f"Failed to fetch Agile forecast: {e}.") from e

        forecast = next(iter(parsed.root), None)
        if forecast is None or not forecast.prices:
            raise APIError(f"No Agile forecast data returned for region {region}.")

        return [
            AgileForecastReading(
                period_from=entry.date_time,
                period_to=entry.date_time + HALF_HOUR,
                unit_rate=entry.agile_pred,
            )
            for entry in forecast.prices
        ]

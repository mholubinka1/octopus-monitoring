from datetime import UTC, datetime, timedelta
from decimal import Decimal

import requests
from common.decorator import retry
from common.exceptions import APIError
from common.http import raise_for_http_error
from data.local_day import LONDON
from data.octopus.model import AgileForecastReading
from pydantic import BaseModel

REQUEST_TIMEOUT_SECONDS = 30
HALF_HOUR = timedelta(minutes=30)


def _to_utc(value: datetime) -> datetime:
    # x2r.uk documents `date` as Europe/London, not UTC -- unlike
    # agilepredict.com's UTC-offset timestamps, a naive value here means
    # local wall-clock time, so it must be interpreted as London before
    # converting, not defaulted to UTC (that would be off by the BST
    # offset). Mirrors local_day.to_local_date's naive-handling shape.
    # One inherent gap: a naive value during the UK's autumn DST "fall
    # back" hour is genuinely ambiguous (that local time occurs twice) --
    # ZoneInfo defaults to the first (BST) occurrence, since x2r.uk's
    # response carries no fold/disambiguation data to resolve it correctly.
    # At most one 30-minute forecast slot a year; not fixable client-side.
    if value.tzinfo is None:
        value = value.replace(tzinfo=LONDON)
    return value.astimezone(UTC)


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

        readings = []
        for entry in parsed.prices.forecast:
            period_from = _to_utc(entry.date)
            readings.append(
                AgileForecastReading(
                    period_from=period_from,
                    period_to=period_from + HALF_HOUR,
                    unit_rate=entry.price,
                )
            )
        return readings

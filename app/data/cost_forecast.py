import logging.config
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from itertools import groupby
from logging import Logger, getLogger
from typing import List, Optional, Protocol

from common.logging import APP_LOGGER_NAME, config
from data.model import CostForecast, DailyCostSummary, Energy
from data.octopus.model import (
    AgileForecastReading,
    Agreement,
    BillingPeriod,
    MeterSource,
    Rate,
    TariffType,
)

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)

TILE_SOURCE_WINDOW_DAYS = 7
HALF_HOURS_PER_DAY = 48


def _midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def project_daily_average_consumption(daily_totals_kwh: List[Decimal]) -> Decimal:
    if not daily_totals_kwh:
        raise ValueError(
            "No elapsed days of consumption to project a future average from."
        )
    return sum(daily_totals_kwh, start=Decimal(0)) / len(daily_totals_kwh)


def tile_forecast_beyond(
    forecast: List[AgileForecastReading], target_end: date
) -> List[AgileForecastReading]:
    if not forecast:
        return []

    by_day = {
        day: list(readings)
        for day, readings in groupby(
            sorted(forecast, key=lambda r: r.period_from),
            key=lambda r: r.period_from.date(),
        )
    }
    real_days = sorted(by_day.keys())
    last_real_day = real_days[-1]
    if target_end <= last_real_day:
        return []

    source_days = real_days[-TILE_SOURCE_WINDOW_DAYS:]

    tiled: List[AgileForecastReading] = []
    day_offset = 1
    while True:
        synthetic_day = last_real_day + timedelta(days=day_offset)
        source_day = source_days[(day_offset - 1) % len(source_days)]
        shift = synthetic_day - source_day
        for reading in by_day[source_day]:
            tiled.append(
                AgileForecastReading(
                    period_from=reading.period_from + shift,
                    period_to=reading.period_to + shift,
                    unit_rate=reading.unit_rate,
                )
            )
        if synthetic_day >= target_end:
            break
        day_offset += 1

    return tiled


class CostForecastSource(MeterSource, Protocol):
    region_code: str

    def get_current_billing_period(self) -> BillingPeriod: ...

    def fetch_agile_forecast(self, region: str) -> List[AgileForecastReading]: ...

    def read_elapsed_billing_period_costs(
        self, period_from: datetime, period_to: datetime
    ) -> List[DailyCostSummary]: ...

    def read_current_product_rate(
        self, product_code: str, region: str, as_of: datetime
    ) -> Optional[Rate]: ...

    def persist_cost_forecast(self, forecast: CostForecast) -> None: ...


class CostForecastRetriever:
    _client: CostForecastSource

    def __init__(self, client: CostForecastSource) -> None:
        self._client = client

    def refresh(self, as_of: Optional[datetime] = None) -> None:
        if as_of is None:
            as_of = datetime.now(timezone.utc)

        billing_period = self._client.get_current_billing_period()
        elapsed_start = _midnight_utc(billing_period.start)

        agreement = self._current_electricity_agreement()
        daily_costs = self._client.read_elapsed_billing_period_costs(
            elapsed_start, as_of
        )
        daily_costs = self._fill_zero_consumption_days(
            billing_period.start, as_of, agreement, daily_costs
        )
        actual_cost_to_date = sum((d.day_cost_gbp for d in daily_costs), Decimal("0"))

        remaining_cost = self._project_remaining_cost(
            billing_period, agreement, daily_costs, as_of
        )

        forecast = CostForecast(
            billing_period_start=billing_period.start,
            billing_period_end=billing_period.end,
            actual_cost_to_date=actual_cost_to_date,
            projected_total_cost=actual_cost_to_date + remaining_cost,
            computed_at=as_of,
        )
        self._client.persist_cost_forecast(forecast)
        logger.info(
            f"Cost forecast refresh: billing period {billing_period.start}-"
            f"{billing_period.end}, actual to date £{actual_cost_to_date}, "
            f"projected total £{forecast.projected_total_cost}."
        )

    def _current_electricity_agreement(self) -> Agreement:
        electricity_meter = next(
            m for m in self._client.meters if m.energy == Energy.electricity
        )
        return next(a for a in electricity_meter.agreements if a.valid_to is None)

    def _fill_zero_consumption_days(
        self,
        billing_period_start: date,
        as_of: datetime,
        agreement: Agreement,
        daily_costs: List[DailyCostSummary],
    ) -> List[DailyCostSummary]:
        # A day with zero consumption rows produces no row from the join in
        # read_elapsed_billing_period_costs -- there's no consumption row to
        # join a standing charge through. The standing charge still accrues
        # for that day regardless of usage, so it's filled in here from
        # whichever product_rate applied at that day's midday.
        present_days = {d.date for d in daily_costs}
        filled = list(daily_costs)
        day = billing_period_start
        while _midnight_utc(day) < as_of:
            if day not in present_days:
                midday = _midnight_utc(day) + timedelta(hours=12)
                rate = self._client.read_current_product_rate(
                    agreement.product_code, self._client.region_code, midday
                )
                if rate is None:
                    logger.warning(
                        f"No product_rate found for {agreement.product_code} "
                        f"on {day} -- omitting its standing charge from "
                        "actual_cost_to_date."
                    )
                else:
                    filled.append(
                        DailyCostSummary(
                            date=day,
                            total_kwh=Decimal("0"),
                            day_cost_gbp=rate.standing_charge / 100,
                        )
                    )
            day += timedelta(days=1)
        return filled

    def _project_remaining_cost(
        self,
        billing_period: BillingPeriod,
        agreement: Agreement,
        daily_costs: List[DailyCostSummary],
        as_of: datetime,
    ) -> Decimal:
        remaining_days = (billing_period.end - as_of.date()).days
        if remaining_days <= 0:
            return Decimal("0")

        future_daily_kwh = project_daily_average_consumption(
            [d.total_kwh for d in daily_costs]
        )
        current_rate = self._client.read_current_product_rate(
            agreement.product_code, self._client.region_code, as_of
        )
        if current_rate is None:
            raise RuntimeError(
                f"No product_rate found for {agreement.product_code} in "
                f"{self._client.region_code} as of {as_of} -- cannot "
                "project remaining billing period cost."
            )

        standing_cost = remaining_days * current_rate.standing_charge

        if agreement.tariff_type == TariffType.agile:
            variable_cost = self._project_agile_variable_cost(
                billing_period.end, future_daily_kwh, as_of
            )
        else:
            variable_cost = remaining_days * future_daily_kwh * current_rate.unit_rate

        return (variable_cost + standing_cost) / 100

    def _project_agile_variable_cost(
        self, billing_period_end: date, future_daily_kwh: Decimal, as_of: datetime
    ) -> Decimal:
        forecast_readings = self._client.fetch_agile_forecast(self._client.region_code)
        end_datetime = _midnight_utc(billing_period_end)
        tiled = tile_forecast_beyond(forecast_readings, billing_period_end)
        remaining_readings = [
            r
            for r in forecast_readings + tiled
            if as_of <= r.period_from < end_datetime
        ]
        per_slot_kwh = future_daily_kwh / HALF_HOURS_PER_DAY
        return sum(
            (per_slot_kwh * r.unit_rate for r in remaining_readings), Decimal("0")
        )

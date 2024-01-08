from datetime import datetime, timedelta
from typing import List

from data.api import Consumption, OctopusAPI
from data.influx import InfluxDB


def write_full_consumption_history(api: OctopusAPI, influxdb: InfluxDB) -> datetime:
    latest_period_to, consumption_history = extract_consumption_history(api)
    yesterday = extract_yesterday_consumption(api)
    month_to_date = extract_month_to_date_consumption(api)

    influxdb.save_consumption(consumption_history, yesterday, month_to_date)

    return latest_period_to


def write_new_consumption_history(
    period_from: datetime, api: OctopusAPI, influxdb: InfluxDB
) -> datetime:
    new_period_from, new_consumption = extract_new_consumption(api, period_from)
    yesterday = extract_yesterday_consumption(api)
    month_to_date = extract_month_to_date_consumption(api)

    influxdb.save_consumption(new_consumption, yesterday, month_to_date)

    return new_period_from


# region Data Extraction Methods


def extract_consumption_history(api: OctopusAPI) -> tuple[datetime, List[Consumption]]:
    consumption_history = api.get_consumption()
    latest_period_to = consumption_history[0].end
    return latest_period_to, consumption_history


def extract_new_consumption(
    api: OctopusAPI, period_from: datetime
) -> tuple[datetime, List[Consumption]]:
    new_consumption = api.get_consumption(period_from=period_from)
    latest_period_to = new_consumption[0].end
    return latest_period_to, new_consumption


def extract_yesterday_consumption(api: OctopusAPI) -> List[Consumption]:
    yesterday = datetime.utcnow() - timedelta(days=1)
    yesterday = datetime(yesterday.year, yesterday.month, yesterday.day)
    end_of_day = yesterday + timedelta(days=1)
    return api.get_cumulative_consumption(yesterday, end_of_day)


def extract_month_to_date_consumption(api: OctopusAPI) -> List[Consumption]:
    now = datetime.utcnow()
    first_day_of_month = datetime(now.year, now.month, 1)
    return api.get_cumulative_consumption(first_day_of_month, now)


# endregion

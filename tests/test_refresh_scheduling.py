from unittest.mock import Mock

from common.config import RefreshSettings
from data.consumption import ConsumptionRetriever
from main import register_jobs
from schedule import Scheduler


def test_registered_job_runs_on_the_configured_refresh_interval() -> None:
    refresh_config = RefreshSettings(
        {
            "data_refresh": {
                "polling_interval_seconds": 1,
                "refresh_interval_hours": 4,
                "historical_limit_days": 45,
            }
        }
    )
    scheduler = Scheduler()

    job = register_jobs(scheduler, refresh_config, Mock(spec=ConsumptionRetriever))

    assert job.interval == refresh_config.refresh_interval
    assert job.unit == "hours"

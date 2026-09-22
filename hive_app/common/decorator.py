import logging.config
import time
from collections.abc import Callable
from logging import Logger, getLogger
from typing import Any

from hive_app.common.logging import APP_LOGGER_NAME, config

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def retry_with_exponential_backoff(
    max_attempts: int = 5, base_delay_seconds: int = 60, multiplier: int = 2
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    def decorator(func: Callable[..., None]) -> Callable[..., None]:
        def wrapper(*args: Any, **kwargs: Any) -> None:
            delay = base_delay_seconds
            for attempt in range(1, max_attempts + 1):
                try:
                    func(*args, **kwargs)
                    return
                except Exception as e:
                    if attempt == max_attempts:
                        logger.exception(
                            f"Error attempting to execute {func.__qualname__}. "
                            f"Retries exhausted after {max_attempts} attempts; "
                            "giving up until the next scheduled run."
                        )
                        return
                    logger.warning(
                        f"Error attempting to execute {func.__qualname__}: {e}. "
                        f"Retrying in {delay} seconds "
                        f"(attempt {attempt}/{max_attempts}).",
                        exc_info=True,
                    )
                    time.sleep(delay)
                    delay *= multiplier

        return wrapper

    return decorator

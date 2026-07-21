import logging.config
import time
from logging import Logger, getLogger
from typing import Any, Callable, Optional

from common.logging import APP_LOGGER_NAME, config

logging.config.dictConfig(config)
logger: Logger = getLogger(APP_LOGGER_NAME)


def retry(
    stop_after: int = 3, retry_delay: int = 10
) -> Callable[[Callable[..., Optional[Any]]], Callable[..., Any]]:
    def decorator(func: Callable[..., Optional[Any]]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            while attempt < stop_after:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error = f"Error attempting to execute {func}: {e}. \nRetrying in {retry_delay} seconds."
                    logger.warning(error)
                    attempt += 1
                    time.sleep(retry_delay)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error = f"Error attempting to execute {func}: {e}. \nRetries exhausted."
                logger.error(error)
                raise e

        return wrapper

    return decorator


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
                        logger.error(
                            f"Error attempting to execute {func.__qualname__}: {e}. "
                            f"Retries exhausted after {max_attempts} attempts; "
                            "giving up until the next scheduled run.",
                            exc_info=True,
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

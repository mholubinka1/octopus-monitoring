from typing import Any, Dict, Optional, Type, TypeVar

import requests
from common.config import OctopusAPISettings
from common.decorator import retry
from common.http import raise_for_http_error
from pydantic import BaseModel

REQUEST_TIMEOUT_SECONDS = 30

T = TypeVar("T", bound=BaseModel)


class OctopusTransport:
    base_url: str = "https://api.octopus.energy/v1/"

    def __init__(self, settings: OctopusAPISettings) -> None:
        # Shared across concurrent background job threads (see
        # _run_with_backoff_in_background in main.py) -- safe without extra
        # locking since urllib3's connection pool is internally locked, and
        # auth is set once here and never mutated per-call.
        self._session = requests.Session()
        self._session.auth = (settings.api_key, "")

    @retry()
    def get(
        self,
        url: str,
        response_model: Type[T],
        params: Optional[Dict[str, Any]] = None,
        description: str = "request",
    ) -> T:
        response: Optional[requests.Response] = None
        try:
            response = self._session.get(
                url=url,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response_model.model_validate(response.json())
        except Exception as e:
            raise_for_http_error(response, e, description)

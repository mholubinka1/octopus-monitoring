from typing import Any, Dict, Optional, Type, TypeVar

import requests
from common.config import OctopusAPISettings
from common.decorator import retry
from common.exceptions import APIError
from pydantic import BaseModel

REQUEST_TIMEOUT_SECONDS = 30

T = TypeVar("T", bound=BaseModel)


class OctopusTransport:
    base_url: str = "https://api.octopus.energy/v1/"

    def __init__(self, settings: OctopusAPISettings) -> None:
        self._api_key = settings.api_key

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
            response = requests.get(
                url=url,
                auth=(self._api_key, ""),
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response_model.model_validate(response.json())
        except Exception as e:
            if response is not None and response.status_code != 200:
                try:
                    error_body: object = response.json()
                except ValueError:
                    error_body = response.text
                raise APIError(error_body) from e
            raise RuntimeError(f"Failed to {description}: {e}.") from e

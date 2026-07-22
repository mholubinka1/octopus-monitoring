from typing import NoReturn, Optional

import requests
from common.exceptions import APIError


def raise_for_http_error(
    response: Optional[requests.Response], error: Exception, description: str
) -> NoReturn:
    if response is not None and response.status_code != 200:
        try:
            error_body: object = response.json()
        except ValueError:
            error_body = response.text
        raise APIError(error_body) from error
    raise RuntimeError(f"Failed to {description}: {error}.") from error

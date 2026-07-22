from datetime import date
from typing import Any, Dict, Optional, Type, TypeVar

import requests
from common.config import OctopusAPISettings
from common.decorator import retry
from common.exceptions import APIError
from common.http import raise_for_http_error
from data.octopus.model import BillingPeriod
from pydantic import BaseModel, ConfigDict, Field

REQUEST_TIMEOUT_SECONDS = 30

T = TypeVar("T", bound=BaseModel)


class ObtainKrakenTokenData(BaseModel):
    token: str


class ObtainKrakenTokenPayload(BaseModel):
    obtainKrakenToken: ObtainKrakenTokenData


class ObtainKrakenTokenResponse(BaseModel):
    data: ObtainKrakenTokenPayload


class BillingOptionsData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    period_start: date = Field(alias="currentBillingPeriodStartDate")
    period_end: Optional[date] = Field(alias="currentBillingPeriodEndDate")
    is_fixed: bool = Field(alias="isFixed")


class AccountPayload(BaseModel):
    billingOptions: BillingOptionsData


class BillingOptionsPayload(BaseModel):
    account: AccountPayload


class BillingOptionsResponse(BaseModel):
    data: BillingOptionsPayload


OBTAIN_KRAKEN_JWT_MUTATION = """
mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    token
  }
}
"""

BILLING_OPTIONS_QUERY = """
query billingOptions($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    billingOptions {
      currentBillingPeriodStartDate
      currentBillingPeriodEndDate
      isFixed
    }
  }
}
"""


class KrakenTransport:
    base_url: str = "https://api.octopus.energy/v1/graphql/"

    @retry()
    def post(
        self,
        query: str,
        variables: Dict[str, Any],
        response_model: Type[T],
        description: str = "request",
        token: Optional[str] = None,
    ) -> T:
        response: Optional[requests.Response] = None
        try:
            headers = {"Authorization": f"JWT {token}"} if token else {}
            response = requests.post(
                url=self.base_url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
            if "errors" in body:
                raise APIError(body["errors"])
            return response_model.model_validate(body)
        except APIError:
            raise
        except Exception as e:
            raise_for_http_error(response, e, description)


class BillingPeriodClient:
    def __init__(
        self, settings: OctopusAPISettings, transport: KrakenTransport
    ) -> None:
        self._account_number = settings.account_number
        self._api_key = settings.api_key
        self._transport = transport

    def get_current_billing_period(self) -> BillingPeriod:
        token = self._mint_token()
        billing_options = self._transport.post(
            BILLING_OPTIONS_QUERY,
            {"accountNumber": self._account_number},
            BillingOptionsResponse,
            description="fetch billing period",
            token=token,
        ).data.account.billingOptions

        return BillingPeriod.from_billing_options(
            billing_options.period_start,
            billing_options.period_end,
            billing_options.is_fixed,
        )

    def _mint_token(self) -> str:
        response = self._transport.post(
            OBTAIN_KRAKEN_JWT_MUTATION,
            {"input": {"APIKey": self._api_key}},
            ObtainKrakenTokenResponse,
            description="mint Kraken token",
        )
        return response.data.obtainKrakenToken.token

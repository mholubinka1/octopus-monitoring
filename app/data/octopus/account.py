import re
from typing import List, Optional, Tuple

from common.config import OctopusAPISettings
from common.exceptions import APIError
from common.utils import is_none_or_whitespace
from data.octopus.model import Account, Electricity, Gas, Meter
from data.octopus.transport import OctopusTransport
from pydantic import BaseModel


class MeterSerialInfo(BaseModel):
    serial_number: str


class AgreementInfo(BaseModel):
    tariff_code: str
    valid_from: str
    valid_to: Optional[str] = None


class ElectricityMeterPointInfo(BaseModel):
    mpan: str
    meters: List[MeterSerialInfo]
    agreements: Optional[List[AgreementInfo]] = None


class GasMeterPointInfo(BaseModel):
    mprn: str
    meters: List[MeterSerialInfo]
    agreements: Optional[List[AgreementInfo]] = None


class PropertyInfo(BaseModel):
    postcode: str
    address_line_1: str = ""
    address_line_2: str = ""
    address_line_3: str = ""
    town: str = ""
    county: str = ""
    electricity_meter_points: List[ElectricityMeterPointInfo] = []
    gas_meter_points: List[GasMeterPointInfo] = []


class AccountMeterInformationResponse(BaseModel):
    properties: List[PropertyInfo]


class GridSupplyPoint(BaseModel):
    group_id: str


class GridSupplyPointsResponse(BaseModel):
    results: List[GridSupplyPoint]


class AccountClient:
    def __init__(
        self, settings: OctopusAPISettings, transport: OctopusTransport
    ) -> None:
        self._account_number = settings.account_number
        self._transport = transport

    def get_account_meter_information(self) -> Tuple[Account, List[Meter]]:
        url = self._transport.base_url + f"accounts/{self._account_number}"
        parsed = self._transport.get(
            url,
            AccountMeterInformationResponse,
            description="fetch account/meter information",
        )

        properties = next(iter(parsed.properties), None)
        if properties is None:
            raise APIError("Account has no properties.")

        postcode = re.sub(r"\s", "", properties.postcode)

        address_lines = [
            properties.address_line_1.strip(),
            properties.address_line_2.strip(),
            properties.address_line_3.strip(),
            properties.town.strip(),
            properties.county.strip(),
        ]
        account = Account(
            self._account_number,
            ", ".join(
                [
                    address_line
                    for address_line in address_lines
                    if not is_none_or_whitespace(address_line)
                ]
            ),
            postcode,
        )

        meters: List[Meter] = []
        if properties.electricity_meter_points:
            meters.append(
                Electricity.from_response(properties.electricity_meter_points)
            )
        if properties.gas_meter_points:
            meters.append(Gas.from_response(properties.gas_meter_points))

        return (account, meters)

    def get_region_code(self, postcode: str) -> str:
        url = self._transport.base_url + "industry/grid-supply-points"
        parsed = self._transport.get(
            url,
            GridSupplyPointsResponse,
            params={"postcode": postcode},
            description=f"fetch region code for {postcode}",
        )
        result = next(iter(parsed.results), None)
        if result is None:
            raise APIError(f"No grid supply point found for postcode {postcode}.")
        return result.group_id

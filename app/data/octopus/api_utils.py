from datetime import datetime
from typing import Dict, List, Optional

from data.octopus.model import Agreement, Electricity, Gas


def to_agreements(json_agreements: Optional[List[Dict]]) -> List[Agreement]:
    if not json_agreements:
        return []
    agreements: List[Agreement] = []
    for json_agreement in json_agreements:
        tariff_code = json_agreement["tariff_code"].upper()
        valid_from = datetime.fromisoformat(json_agreement["valid_from"])
        valid_to_str = json_agreement["valid_to"]
        valid_to = None if not valid_to_str else datetime.fromisoformat(valid_to_str)
        agreements.append(Agreement(tariff_code, valid_from, valid_to))
    return agreements


def to_electricity_meter(electricity_meter_points: List[Dict]) -> Electricity:
    if len(electricity_meter_points) > 1:
        raise NotImplementedError(
            "This software does not currently handle multiple MPANs."
        )

    meter = electricity_meter_points[0]

    sn_meters = meter.get("meters", None)
    if not sn_meters:
        raise ValueError("Meter Serial Number information not available.")
    if len(sn_meters) == 0:
        raise ValueError("Meter Serial Number information not available.")
    if len(sn_meters) > 1:
        raise NotImplementedError(
            "This software does not currently handle multiple SNs per MPAN."
        )

    mpan = meter["mpan"]
    serial_number = sn_meters[0]["serial_number"]
    agreements = to_agreements(meter["agreements"])
    return Electricity(
        mpan=mpan,
        serial_number=serial_number,
        agreements=agreements,
    )


def to_gas_meter(gas_meter_points: List[Dict]) -> Gas:
    if len(gas_meter_points) > 1:
        raise NotImplementedError(
            "This software does not currently handle multiple MPRNs."
        )

    meter = gas_meter_points[0]

    sn_meters = meter.get("meters", None)
    if not sn_meters:
        raise ValueError("Meter Serial Number information not available.")
    if len(sn_meters) == 0:
        raise ValueError("Meter Serial Number information not available.")
    if len(sn_meters) > 1:
        raise NotImplementedError(
            "This software does not currently handle multiple SNs per MPAN."
        )

    mprn = meter["mprn"]
    serial_number = sn_meters[0]["serial_number"]
    agreements = to_agreements(meter["agreements"])
    return Gas(
        mprn=mprn,
        serial_number=serial_number,
        agreements=agreements,
    )

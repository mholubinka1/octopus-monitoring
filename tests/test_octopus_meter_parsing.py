from typing import List, Optional

import pytest
from common.exceptions import ArgumentError, NullValueError
from data.octopus.account import (
    AgreementInfo,
    ElectricityMeterPointInfo,
    GasMeterPointInfo,
    MeterSerialInfo,
)
from data.octopus.model import Agreement, Electricity, Gas

VALID_AGREEMENT = AgreementInfo(
    tariff_code="E-1R-VAR-22-11-01-A",
    valid_from="2022-11-01T00:00:00+00:00",
    valid_to=None,
)


def _electricity_meter_point(
    meters: Optional[List[MeterSerialInfo]] = None,
    agreements: Optional[List[AgreementInfo]] = None,
    mpan: str = "1234567890123",
) -> ElectricityMeterPointInfo:
    return ElectricityMeterPointInfo(
        mpan=mpan,
        meters=(
            meters
            if meters is not None
            else [MeterSerialInfo(serial_number="00A1234567")]
        ),
        agreements=agreements if agreements is not None else [VALID_AGREEMENT],
    )


def _gas_meter_point(
    meters: Optional[List[MeterSerialInfo]] = None,
    agreements: Optional[List[AgreementInfo]] = None,
    mprn: str = "9876543210987",
) -> GasMeterPointInfo:
    return GasMeterPointInfo(
        mprn=mprn,
        meters=(
            meters
            if meters is not None
            else [MeterSerialInfo(serial_number="00G7654321")]
        ),
        agreements=agreements if agreements is not None else [VALID_AGREEMENT],
    )


def test_electricity_from_response_builds_a_meter_from_a_valid_single_meter_point() -> (
    None
):
    meter = Electricity.from_response([_electricity_meter_point()])

    assert meter.mpan == "1234567890123"
    assert meter.serial_number == "00A1234567"
    assert len(meter.agreements) == 1


def test_gas_from_response_builds_a_meter_from_a_valid_single_meter_point() -> None:
    meter = Gas.from_response([_gas_meter_point()])

    assert meter.mprn == "9876543210987"
    assert meter.serial_number == "00G7654321"
    assert len(meter.agreements) == 1


def test_electricity_from_response_raises_on_no_meter_points() -> None:
    with pytest.raises(NullValueError):
        Electricity.from_response([])


def test_gas_from_response_raises_on_no_meter_points() -> None:
    with pytest.raises(NullValueError):
        Gas.from_response([])


def test_electricity_from_response_raises_on_multiple_mpans() -> None:
    with pytest.raises(ArgumentError, match="multiple MPANs"):
        Electricity.from_response(
            [_electricity_meter_point(mpan="111"), _electricity_meter_point(mpan="222")]
        )


def test_gas_from_response_raises_on_multiple_mprns() -> None:
    with pytest.raises(ArgumentError, match="multiple MPRNs"):
        Gas.from_response([_gas_meter_point(mprn="111"), _gas_meter_point(mprn="222")])


def test_electricity_from_response_raises_on_missing_serial_number() -> None:
    with pytest.raises(NullValueError):
        Electricity.from_response([_electricity_meter_point(meters=[])])


def test_gas_from_response_raises_on_missing_serial_number() -> None:
    with pytest.raises(NullValueError):
        Gas.from_response([_gas_meter_point(meters=[])])


def test_electricity_from_response_raises_on_multiple_serial_numbers() -> None:
    with pytest.raises(ArgumentError, match="multiple SNs per MPAN"):
        Electricity.from_response(
            [
                _electricity_meter_point(
                    meters=[
                        MeterSerialInfo(serial_number="A"),
                        MeterSerialInfo(serial_number="B"),
                    ]
                )
            ]
        )


def test_gas_from_response_raises_on_multiple_serial_numbers() -> None:
    with pytest.raises(ArgumentError, match="multiple SNs per MPRN"):
        Gas.from_response(
            [
                _gas_meter_point(
                    meters=[
                        MeterSerialInfo(serial_number="A"),
                        MeterSerialInfo(serial_number="B"),
                    ]
                )
            ]
        )


def test_electricity_from_response_raises_on_empty_agreements() -> None:
    with pytest.raises(ArgumentError, match="tariff information"):
        Electricity.from_response([_electricity_meter_point(agreements=[])])


def test_gas_from_response_raises_on_empty_agreements() -> None:
    with pytest.raises(ArgumentError, match="tariff information"):
        Gas.from_response([_gas_meter_point(agreements=[])])


def test_agreement_from_response_parses_valid_to_as_none_when_ongoing() -> None:
    agreement = Agreement.from_response(VALID_AGREEMENT)

    assert agreement.tariff_code == "E-1R-VAR-22-11-01-A"
    assert agreement.valid_to is None


def test_agreement_from_response_parses_a_bounded_valid_to() -> None:
    info = AgreementInfo(
        tariff_code="E-1R-VAR-22-11-01-A",
        valid_from="2022-11-01T00:00:00+00:00",
        valid_to="2023-05-01T00:00:00+00:00",
    )

    agreement = Agreement.from_response(info)

    assert agreement.valid_to is not None

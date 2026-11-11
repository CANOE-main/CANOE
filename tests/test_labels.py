from enum import Enum

import pytest

from canoe.common import CANOEFuel, CANOEProvince, CANOESector

ENUMS: list[type[CANOEFuel] | type[CANOEProvince] | type[CANOESector]] = [
    CANOEFuel,
    CANOEProvince,
    CANOESector,
]


@pytest.mark.parametrize("enum", ENUMS)
def test_every_member_from_its_value_and_name_in_any_format(enum: type[Enum]):
    for member in enum:
        for text in (
            str(member.value),
            member.name,
            member.name.upper(),
            member.name.lower().replace("_", " "),
        ):
            assert enum.from_str(text) is member  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    ("enum", "text", "expected"),
    [
        (CANOEProvince, "PE", CANOEProvince.PRINCE_EDWARD_ISLAND),
        (CANOEProvince, "nl", CANOEProvince.NEWFOUNDLAND_AND_LABRADOR),
        (CANOEProvince, "Québec", None),
        (CANOESector, "Electric Power", CANOESector.Electricity),
        (CANOESector, "t", CANOESector.Transportation),
        (CANOESector, "transport", CANOESector.Transportation),
        (CANOEFuel, "heavy-fuel-oil", CANOEFuel.HeavyFuelOil),
        (CANOEFuel, "Liquefied Petroleum Gas", CANOEFuel.LiquifiedPretroleumGas),
    ],
)
def test_aliases(enum: type[Enum], text: str, expected: Enum | None):
    if expected is None:
        with pytest.raises(ValueError, match="Unknown province"):
            enum.from_str(text)  # pyright: ignore[reportAttributeAccessIssue]
    else:
        assert enum.from_str(text) is expected  # pyright: ignore[reportAttributeAccessIssue]


def test_unknown_labels_list_the_codes():
    with pytest.raises(ValueError, match="Unknown fuel 'kerosene'.*NG"):
        CANOEFuel.from_str("kerosene")

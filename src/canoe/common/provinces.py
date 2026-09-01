from enum import StrEnum
from typing import override


class CANOEProvince(StrEnum):
    ALBERTA = "Alberta"
    BRITISH_COLUMBIA = "British Columbia"
    MANITOBA = "Manitoba"
    NEW_BRUNSWICK = "New Brunswick"
    NEWFOUNDLAND_AND_LABRADOR = "Newfoundland and Labrador"
    NOVA_SCOTIA = "Nova Scotia"
    ONTARIO = "Ontario"
    PRINCE_EDWARD_ISLAND = "Prince Edward Island"
    QUEBEC = "Quebec"
    SASKATCHEWAN = "Saskatchewan"

    @override
    @classmethod
    def _missing_(cls, value: object):
        _ALIASES = {
            "AB": cls.ALBERTA,
            "Alberta": cls.ALBERTA,
            "BC": cls.BRITISH_COLUMBIA,
            "British Columbia": cls.BRITISH_COLUMBIA,
            "MB": cls.MANITOBA,
            "Manitoba": cls.MANITOBA,
            "NB": cls.NEW_BRUNSWICK,
            "New Brunswick": cls.NEW_BRUNSWICK,
            "NLLAB": cls.NEWFOUNDLAND_AND_LABRADOR,
            "Newfoundland and Labrador": cls.NEWFOUNDLAND_AND_LABRADOR,
            "NS": cls.NOVA_SCOTIA,
            "Nova Scotia": cls.NOVA_SCOTIA,
            "ON": cls.ONTARIO,
            "Ontario": cls.ONTARIO,
            "PEI": cls.PRINCE_EDWARD_ISLAND,
            "Prince Edward Island": cls.PRINCE_EDWARD_ISLAND,
            "QC": cls.QUEBEC,
            "Quebec": cls.QUEBEC,
            "SK": cls.SASKATCHEWAN,
            "Saskatchewan": cls.SASKATCHEWAN,
        }
        return _ALIASES.get(str(value))

    def short(self):
        SHORT = {
            CANOEProvince.ALBERTA: "AB",
            CANOEProvince.BRITISH_COLUMBIA: "BC",
            CANOEProvince.MANITOBA: "MB",
            CANOEProvince.NEW_BRUNSWICK: "NB",
            CANOEProvince.NEWFOUNDLAND_AND_LABRADOR: "NLLAB",
            CANOEProvince.NOVA_SCOTIA: "NS",
            CANOEProvince.ONTARIO: "ON",
            CANOEProvince.PRINCE_EDWARD_ISLAND: "PEI",
            CANOEProvince.QUEBEC: "QC",
            CANOEProvince.SASKATCHEWAN: "SK",
        }
        return SHORT[self]

    def is_atlantic(self) -> bool:
        return self in [
            CANOEProvince.PRINCE_EDWARD_ISLAND,
            CANOEProvince.NEW_BRUNSWICK,
            CANOEProvince.NOVA_SCOTIA,
            CANOEProvince.NEWFOUNDLAND_AND_LABRADOR,
        ]

    def get_nrcan_code(self) -> str:
        if self.is_atlantic():
            return "ATL"
        if self == CANOEProvince.BRITISH_COLUMBIA:
            return "BC"  # The real one is BCT but for accessing the cache this is what we need
        return self.short()

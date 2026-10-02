from enum import StrEnum
from typing import Any, override


class CANOESector(StrEnum):
    Commercial = "COM"
    Residential = "RES"
    Industry = "IND"
    Transportation = "TRP"
    Agriculture = "AGR"
    Electricity = "ELC"
    Fuel = "FUEL"

    @classmethod
    @override
    def _missing_(cls, value: Any):
        if isinstance(value, str) and value in cls.__members__:
            return cls.__members__[value]
        for member in cls:
            if value == member.get_tag():
                return member
        return None

    def get_tag(self):
        _TAGS = {
            "COM": "C",
            "RES": "R",
            "IND": "I",
            "TRP": "T",
            "AGR": "A",
            "ELC": "E",
            "FUEL": "F",
        }
        return _TAGS[self.value]

    def get_eia_sector(self) -> str | None:
        """
        Sector of the EIA AEO Table 3 'Energy Prices' series, if EIA has one.

        Examples
        --------
        >>> CANOESector.Electricity.get_eia_sector()
        'Electric Power'
        >>> CANOESector.Agriculture.get_eia_sector() is None
        True
        """
        EIA_SECTORS: dict[CANOESector, str] = {
            CANOESector.Commercial: "Commercial",
            CANOESector.Residential: "Residential",
            CANOESector.Industry: "Industrial",
            CANOESector.Transportation: "Transportation",
            CANOESector.Electricity: "Electric Power",
        }
        return EIA_SECTORS.get(self)

    @override
    def __str__(self):
        return str(self.name)

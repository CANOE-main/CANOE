from enum import StrEnum
from typing import Any, override

from .labels import match_label


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

    @classmethod
    def from_str(cls, text: str) -> "CANOESector":
        """
        The sector `text` names: its code (`"COM"`), name (`"Commercial"`), tag
        (`"C"`) or EIA name (`"Electric Power"`), in any case and with any
        separators.

        Raises
        ------
        ValueError
            If `text` names no sector.

        Examples
        --------
        >>> [CANOESector.from_str(t) for t in ["ind", "Industry", "industrial", "I"]]
        [<CANOESector.Industry: 'IND'>, <CANOESector.Industry: 'IND'>, <CANOESector.Industry: 'IND'>, <CANOESector.Industry: 'IND'>]
        """
        ALIASES: dict[CANOESector, list[str]] = {
            CANOESector.Transportation: ["transport"],
            CANOESector.Agriculture: ["agricultural"],
        }
        return match_label(
            text,
            {
                sector: [
                    sector.value,
                    sector.name,
                    sector.get_tag(),
                    *([eia] if (eia := sector.get_eia_sector()) else []),
                    *ALIASES.get(sector, []),
                ]
                for sector in cls
            },
            "sector",
        )

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

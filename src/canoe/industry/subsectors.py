"""
Subsectors of the CANOE industry sector: the industries of the NRCan CEUD industry
tables, each modelled as its own demand and technology.
"""

from enum import StrEnum
from typing import override


class IndustrySubsector(StrEnum):
    """
    Industries of the NRCan CEUD industry tables. Configs take the value (e.g.
    `"pulp and paper"`), the key of the subsector's table in the TOML.
    """

    Construction = "construction"
    """Construction."""

    PulpAndPaper = "pulp and paper"
    """Pulp and paper manufacturing."""

    SmeltingAndRefining = "smelting and refining"
    """Smelting and refining of aluminum and other non-ferrous metals."""

    PetroleumRefining = "petroleum refining"
    """Refined petroleum products manufacturing."""

    Cement = "cement"
    """Cement manufacturing."""

    Chemicals = "chemicals"
    """Chemicals manufacturing."""

    IronAndSteel = "iron and steel"
    """Iron and steel manufacturing."""

    OtherManufacturing = "other manufacturing"
    """All other manufacturing."""

    Forestry = "forestry"
    """Forestry, logging and support activities."""

    Mining = "mining"
    """Mining, quarrying, and oil and gas extraction."""

    def short_desc(self) -> str:
        """
        Short description in the names of the subsector's technology and demand
        (e.g. `I_PULP`, `I_D_PULP`), as in the previous module.

        Examples
        --------
        >>> IndustrySubsector.OtherManufacturing.short_desc()
        'OTH_MAN'
        """
        SHORT_DESCS: dict[IndustrySubsector, str] = {
            IndustrySubsector.Construction: "CON",
            IndustrySubsector.PulpAndPaper: "PULP",
            IndustrySubsector.SmeltingAndRefining: "SMELT",
            IndustrySubsector.PetroleumRefining: "REFINING",
            IndustrySubsector.Cement: "CEMENT",
            IndustrySubsector.Chemicals: "CHEM",
            IndustrySubsector.IronAndSteel: "STEEL",
            IndustrySubsector.OtherManufacturing: "OTH_MAN",
            IndustrySubsector.Forestry: "FOR",
            IndustrySubsector.Mining: "MINING",
        }
        return SHORT_DESCS[self]

    def get_desc_name(self) -> str:
        """
        Name of the subsector in descriptions and notes.

        Examples
        --------
        >>> IndustrySubsector.Mining.get_desc_name()
        'mining, quarrying, and oil and gas extraction'
        """
        if self == IndustrySubsector.Mining:
            return "mining, quarrying, and oil and gas extraction"
        return self.value

    @override
    def __str__(self):
        return str(self.name)

    @override
    def __repr__(self):
        return str(self.name)

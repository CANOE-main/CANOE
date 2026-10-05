"""
US census divisions. US data sources (e.g. the EIA AEO technology menus) publish
values by census division, and each province takes those of a comparable division.
"""

from enum import StrEnum


class USCensusDivision(StrEnum):
    """US census divisions; configs take the value (e.g. `"new england"`)."""

    NewEngland = "new england"
    MiddleAtlantic = "middle atlantic"
    EastNorthCentral = "east north central"
    WestNorthCentral = "west north central"
    SouthAtlantic = "south atlantic"
    EastSouthCentral = "east south central"
    WestSouthCentral = "west south central"
    Mountain = "mountain"
    Pacific = "pacific"

    def get_aeo_number(self) -> int:
        """
        Code of the division in the EIA AEO tables (where 11 marks the national
        rows).

        Examples
        --------
        >>> USCensusDivision.EastNorthCentral.get_aeo_number()
        3
        """
        AEO_NUMBERS: dict[USCensusDivision, int] = {
            USCensusDivision.NewEngland: 1,
            USCensusDivision.MiddleAtlantic: 2,
            USCensusDivision.EastNorthCentral: 3,
            USCensusDivision.WestNorthCentral: 4,
            USCensusDivision.SouthAtlantic: 5,
            USCensusDivision.EastSouthCentral: 6,
            USCensusDivision.WestSouthCentral: 7,
            USCensusDivision.Mountain: 8,
            USCensusDivision.Pacific: 9,
        }
        return AEO_NUMBERS[self]

"""
Residential end uses: the demands of the residential sector.

Lives in its own module (instead of `config.py`) so that data and build modules can use
it at runtime without importing the configuration, which imports `build.py`.
"""

from enum import StrEnum
from typing import override


class ResidentialEndUse(StrEnum):
    """
    End uses of the residential sector, one demand each. Space heating, space
    cooling and water heating are energy services (PJ), lighting is light (Glmy) and
    appliances are appliances in use (Munity).
    """

    SpaceHeating = "space heating"
    SpaceCooling = "space cooling"
    WaterHeating = "water heating"
    Lighting = "lighting"
    Refrigerators = "refrigerators"
    Freezers = "freezers"
    DishWashers = "dish washers"
    ClothesWashers = "clothes washers"
    ClothesDryers = "clothes dryers"
    CookingRanges = "cooking ranges"
    OtherAppliances = "other appliances"
    """Other electrical appliances and devices."""

    def short_desc(self) -> str:
        """
        Short description in the name of the end use's demand (e.g. `R_D_SPH`) and
        technologies.

        Examples
        --------
        >>> ResidentialEndUse.CookingRanges.short_desc()
        'APP_COOK_RNG'
        """
        SHORT_DESCS: dict[ResidentialEndUse, str] = {
            ResidentialEndUse.SpaceHeating: "SPH",
            ResidentialEndUse.SpaceCooling: "SPC",
            ResidentialEndUse.WaterHeating: "WAH",
            ResidentialEndUse.Lighting: "LGT",
            ResidentialEndUse.Refrigerators: "APP_REF",
            ResidentialEndUse.Freezers: "APP_FRZ",
            ResidentialEndUse.DishWashers: "APP_DSH",
            ResidentialEndUse.ClothesWashers: "APP_CWSH",
            ResidentialEndUse.ClothesDryers: "APP_CDRY",
            ResidentialEndUse.CookingRanges: "APP_COOK_RNG",
            ResidentialEndUse.OtherAppliances: "APP_OTH",
        }
        return SHORT_DESCS[self]

    def is_appliance(self) -> bool:
        """
        Examples
        --------
        >>> ResidentialEndUse.Freezers.is_appliance(), ResidentialEndUse.Lighting.is_appliance()
        (True, False)
        """
        return self in APPLIANCES

    @override
    def __str__(self):
        return str(self.name)

    @override
    def __repr__(self):
        return str(self.name)


APPLIANCES: tuple[ResidentialEndUse, ...] = (
    ResidentialEndUse.Refrigerators,
    ResidentialEndUse.Freezers,
    ResidentialEndUse.DishWashers,
    ResidentialEndUse.ClothesWashers,
    ResidentialEndUse.ClothesDryers,
    ResidentialEndUse.CookingRanges,
    ResidentialEndUse.OtherAppliances,
)
"""End uses of the appliances table of the configuration."""

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

    def get_desc_name(self) -> str:
        """
        Name of the end use in descriptions and notes.

        Examples
        --------
        >>> ResidentialEndUse.OtherAppliances.get_desc_name()
        'other electrical appliances and devices'
        """
        if self == ResidentialEndUse.OtherAppliances:
            return "other electrical appliances and devices"
        return self.value

    def demand_units(self) -> str:
        """
        Units of the demand: energy services in PJ, light in Glmy (giga lumen-years),
        appliances in use in Munity (million unit-years).

        Examples
        --------
        >>> [e.demand_units() for e in (ResidentialEndUse.SpaceHeating, ResidentialEndUse.Lighting, ResidentialEndUse.Freezers)]
        ['PJ', 'Glmy', 'Munity']
        """
        if self == ResidentialEndUse.Lighting:
            return "Glmy"
        if self.is_appliance():
            return "Munity"
        return "PJ"

    def capacity_units(self) -> str:
        """
        Units of the capacity of the technologies serving the end use: thousand units
        (kunit) of space and water heating and cooling equipment, giga lumens (Glm)
        of lamps, million units (Munit) of appliances. With a capacity to activity
        of 1, a unit of capacity running all year serves a unit of demand.

        Examples
        --------
        >>> [e.capacity_units() for e in (ResidentialEndUse.SpaceHeating, ResidentialEndUse.Lighting, ResidentialEndUse.Freezers)]
        ['kunit', 'Glm', 'Munit']
        """
        if self == ResidentialEndUse.Lighting:
            return "Glm"
        if self.is_appliance():
            return "Munit"
        return "kunit"

    def get_aeo_end_use(self) -> int | None:
        """
        Number of the end use in the AEO residential technology menu; None for those
        it does not cover (lighting, other appliances).

        Examples
        --------
        >>> ResidentialEndUse.WaterHeating.get_aeo_end_use()
        5
        """
        AEO_END_USES: dict[ResidentialEndUse, int] = {
            ResidentialEndUse.SpaceHeating: 1,
            ResidentialEndUse.SpaceCooling: 2,
            ResidentialEndUse.ClothesWashers: 3,
            ResidentialEndUse.DishWashers: 4,
            ResidentialEndUse.WaterHeating: 5,
            ResidentialEndUse.CookingRanges: 6,
            ResidentialEndUse.ClothesDryers: 7,
            ResidentialEndUse.Refrigerators: 8,
            ResidentialEndUse.Freezers: 9,
        }
        return AEO_END_USES.get(self)

    def is_appliance(self) -> bool:
        """
        Examples
        --------
        >>> ResidentialEndUse.Freezers.is_appliance(), ResidentialEndUse.Lighting.is_appliance()
        (True, False)
        """
        return self in ResidentialEndUse.appliances()

    @classmethod
    def appliances(cls) -> tuple["ResidentialEndUse", ...]:
        """End uses of the appliances table of the configuration"""
        return (
            cls.Refrigerators,
            cls.Freezers,
            cls.DishWashers,
            cls.ClothesWashers,
            cls.ClothesDryers,
            cls.CookingRanges,
            cls.OtherAppliances,
        )

    @override
    def __str__(self):
        return str(self.name)

    @override
    def __repr__(self):
        return str(self.name)

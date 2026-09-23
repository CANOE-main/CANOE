"""
Utility functions to standardize naming conventions.
"""

from enum import StrEnum

from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.emissions import CANOEEmission


class TechnologyCapacityScope(StrEnum):
    New = "NEW"
    Existing = "EXS"


class DatasetIdentifier:
    def __init__(
        self, sector: CANOESector, code_description: str, version: str
    ) -> None:
        self.sector: CANOESector = sector
        self.code_description: str = code_description
        self.version: str = version

    def get_dataset_code(
        self,
        province: CANOEProvince | None = None,
    ) -> str:
        province_str = province.short() if province is not None else ""
        sector_str = self.sector.value
        return f"{sector_str}{self.code_description}{province_str}{self.version}"


def get_dataset_code(
    sector: CANOESector,
    resolution_str: str,
    version_code: str,
    province: CANOEProvince | None = None,
) -> str:
    province_str = province.short() if province is not None else ""
    sector_str = sector.value
    return f"{sector_str}{resolution_str}{province_str}{version_code}"


def hour_str(hour: int) -> str:
    return f"H{hour:02d}"


def season_str(season: int) -> str:
    return f"D{season:03d}"


def get_commodity_name(
    sector: CANOESector, short_name: str, is_demand: bool = False
) -> str:
    sector_tag = sector.get_tag()
    return f"{sector_tag}_{'D_' if is_demand else ''}{short_name}"


# def get_fuel_serving_technology_input_commodity(
#     sector: CANOESector,
#     short_name: str,
#     fuel: CANOEFuel,
#     capacity_scope: TechnologyCapacityScope | None = None,
# ) -> str:
#     sector_tag = sector.get_tag()
#     return f"{sector_tag}_{short_name}_{fuel.value.upper()}" + (
#         f"-{capacity_scope.value}" if capacity_scope is not None else ""
#     )


def get_fuel_commodity_in_sector(sector: CANOESector, fuel: CANOEFuel) -> str:
    sector_tag = sector.get_tag()
    return f"{sector_tag}_{fuel.value.lower()}"


def get_emission_commodity_name(emission: CANOEEmission) -> str:
    """
    Emission commodities are shared by all sectors.

    Examples
    --------
    >>> get_emission_commodity_name(CANOEEmission.CH4)
    'ch4'
    """
    return emission.value.lower()


def get_co2_equivalent_commodity_name() -> str:
    """CO2-equivalent commodity, derived from the gases by the central emissions step"""
    return "co2e"

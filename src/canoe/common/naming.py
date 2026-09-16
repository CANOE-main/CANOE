"""
Utility functions to standardize naming conventions.
"""

from enum import StrEnum

from canoe.common import CANOEProvince, CANOESector


class TechnologyCapacityScope(StrEnum):
    New = "NEW"
    Existing = "EXS"


class DatasetIdentifier:
    def __init__(
        self, sector: CANOESector, code_description: str, version: str
    ) -> None:
        self.sector = sector
        self.code_description = code_description
        self.version = version

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

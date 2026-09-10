"""
Utility functions to standardize naming conventions.
"""

from canoe.common import CANOEProvince, CANOESector


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

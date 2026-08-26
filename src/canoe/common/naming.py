"""
Utility functions to standardize naming conventions.
"""

from canoe.common import CANOEProvince, CANOESector


def get_dataset_code(
    sector: CANOESector,
    resolution_str: str,
    version_code: str,
    province: CANOEProvince | None,
) -> str:
    province_str = province.short() if province is not None else ""
    sector_str = sector.value
    return f"{sector_str}{resolution_str}{province_str}{version_code}"

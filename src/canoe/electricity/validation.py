"""
Pre-run validation for canoe-electricity.

Combines the read-only checks of `canoe.common.validation` that the electricity
config needs, before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe.common import CANOEFuelImport
from canoe.common.validation import (
    check_import_provinces,
    check_missing_periods,
    check_missing_regions,
    check_sector_fuel_commodities,
)

if TYPE_CHECKING:
    from .config import CANOEElectricityConfig


def validate_db_against_config(
    config: "CANOEElectricityConfig",
    imports: list[CANOEFuelImport],
    db_conn: Connection,
):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.

    params:
    - imports: the electricity imports the module supplies
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)
    # The delivery technologies output the sectors' electricity commodities
    check_sector_fuel_commodities(
        db_conn, [(i.sector, i.fuel) for i in imports], behavior
    )
    check_import_provinces(imports, config.provinces, behavior)

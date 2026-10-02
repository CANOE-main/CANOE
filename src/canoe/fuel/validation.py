"""
Pre-run validation for canoe-fuel.

Combines the read-only checks of `canoe.common.validation` that the fuel config needs,
before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe_schema.v4_0.models import Commodity

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.naming import get_fuel_commodity_in_sector
from canoe.common.validation import (
    ValidationBehavior,
    check_emission_commodities,
    check_missing_periods,
    check_missing_regions,
    handle_validation_issue,
)

if TYPE_CHECKING:
    from .config import CANOEFuelConfig


def validate_db_against_config(
    config: "CANOEFuelConfig",
    imports: list[CANOEFuelImport],
    db_conn: Connection,
):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.

    params:
    - imports: the fuel imports the module supplies
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)
    # Upstream and combustion emissions are written on the fuel technologies
    check_emission_commodities(db_conn, behavior)
    check_sector_fuel_commodities(
        db_conn, [(i.sector, i.fuel) for i in imports], behavior
    )
    check_import_provinces(imports, config.provinces, behavior)


def check_import_provinces(
    imports: list[CANOEFuelImport],
    provinces: list[CANOEProvince],
    behavior: ValidationBehavior = "error",
):
    """
    Checks that the fuel imports are in the provinces of this module (a sector
    config can set its own provinces).
    """
    outside = [
        f"{str(i.sector).lower()} {i.fuel.get_desc_name()} in {p.short()}"
        for i in imports
        for p in i.provinces
        if p not in provinces
    ]
    if outside:
        handle_validation_issue(
            f"Fuel imports outside the fuel module's provinces: {outside}", behavior
        )


def check_sector_fuel_commodities(
    db_conn: Connection,
    supplied: list[tuple[CANOESector, CANOEFuel]],
    behavior: ValidationBehavior = "error",
):
    """
    Checks that the fuel commodity of every supplied (sector, fuel), e.g. `C_ng`,
    exists in the commodity table: the sectors register them, and the distribution
    technologies output them.
    """
    db_commodities = {
        row[0]
        for row in db_conn.execute(
            f"SELECT name FROM {Commodity.__table_name__}"
        ).fetchall()
    }
    missing = [
        get_fuel_commodity_in_sector(sector, fuel)
        for sector, fuel in supplied
        if get_fuel_commodity_in_sector(sector, fuel) not in db_commodities
    ]
    if missing:
        handle_validation_issue(
            f"Sector fuel commodities {missing} are absent from the commodity table. "
            + "The sectors must register the fuels they import before this module runs.",
            behavior,
        )

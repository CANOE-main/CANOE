"""
Pre-run validation for canoe-commercial.

Combines the read-only checks of `canoe.common.validation` that the commercial config
needs, before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe.common.validation import (
    check_emission_commodities,
    check_missing_periods,
    check_missing_regions,
    check_missing_time_slices,
)

if TYPE_CHECKING:
    from .config import CANOECommercialConfig


def validate_db_against_config(config: "CANOECommercialConfig", db_conn: Connection):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)

    if config.include_dsd:
        check_missing_time_slices(db_conn, config.dsd_time_slices, behavior)

    if config.include_emissions:
        check_emission_commodities(db_conn, behavior)

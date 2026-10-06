"""
Pre-run validation for canoe-residential.

Combines the read-only checks of `canoe.common.validation` that the residential
config needs, before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe.common.validation import (
    check_missing_existing_periods,
    check_missing_periods,
    check_missing_regions,
    check_missing_time_slices,
)

if TYPE_CHECKING:
    from .config import CANOEResidentialConfig


def validate_db_against_config(config: "CANOEResidentialConfig", db_conn: Connection):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)
    if config.include_dsd:
        check_missing_time_slices(db_conn, config.dsd_time_slices, behavior)


def validate_existing_vintages(
    config: "CANOEResidentialConfig", db_conn: Connection, vintages: list[int]
):
    """
    Validate that the existing vintages of the existing stock are existing periods
    of the canoe-base DB (they depend on the lifetimes, known once the data is read).
    """
    check_missing_existing_periods(db_conn, vintages, config.validation_behavior)

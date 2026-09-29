"""
Pre-run validation for canoe-fuel.

Combines the read-only checks of `canoe.common.validation` that the fuel config needs,
before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe.common.validation import (
    check_emission_commodities,
    check_missing_periods,
    check_missing_regions,
)

if TYPE_CHECKING:
    from .config import CANOEFuelConfig


def validate_db_against_config(config: "CANOEFuelConfig", db_conn: Connection):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)
    # Upstream and combustion emissions are written on the fuel technologies
    check_emission_commodities(db_conn, behavior)
    # TODO: check that the sector fuel commodities the distribution technologies
    # output (C_ng, A_dsl, ...) exist; the sectors register them

"""
Pre-run validation for canoe-agriculture.

Combines the read-only checks of `canoe.common.validation` that the agriculture config
needs, before any writes.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING

from canoe.common.validation import check_missing_periods, check_missing_regions

if TYPE_CHECKING:
    from .config import CANOEAgricultureConfig


def validate_db_against_config(config: "CANOEAgricultureConfig", db_conn: Connection):
    """
    Validate the canoe-base DB against this module's config before any writes.
    Raises ValueError on missing structure unless validation_behavior='warning'.
    """
    behavior = config.validation_behavior

    check_missing_periods(db_conn, config.future_periods, behavior)
    check_missing_regions(db_conn, config.provinces, behavior)

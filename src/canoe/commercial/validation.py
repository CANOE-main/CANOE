"""
Pre-run and post-run validation for canoe-commercial.

All functions here are read-only against the database. They check that the DB
produced by canoe-base contains the structure this module's config expects,
and fail loudly (or warn) rather than silently writing wrong data.
"""

from sqlite3 import Connection
from typing import TYPE_CHECKING, Literal

import numpy as np
from canoe_schema.v4_0.models import (
    Commodity,
    Region,
    TimeOfDay,
    TimePeriod,
    TimeSeason,
)
from loguru import logger

from canoe.common import CANOEProvince
from canoe.common.time_slices import CANOETimeSliceSet

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
        check_emission_commodity(db_conn, config.EPA_emission_commodity, behavior)


def check_missing_periods(
    db_conn: Connection,
    future_periods: list[int],
    behavior: Literal["error", "warning"] = "error",
):
    """
    Checks that every future model period exists in time_period with flag='f'.
    """
    cursor = db_conn.cursor()
    db_periods = {
        row[0]
        for row in cursor.execute(
            f"SELECT period FROM {TimePeriod.__table_name__} WHERE flag = 'f'"
        ).fetchall()
    }
    missing = [p for p in future_periods if p not in db_periods]
    if missing:
        _handle(
            f"Future periods {missing} are absent from time_period (flag='f'). "
            + "canoe-base must seed all model periods before this module runs.",
            behavior,
        )


def check_missing_regions(
    db_conn: Connection,
    provinces: list[CANOEProvince],
    behavior: Literal["error", "warning"] = "error",
):
    """
    Checks that every province in the module's region list exists in the region table.
    """
    cursor = db_conn.cursor()
    db_regions = [
        row[0]
        for row in cursor.execute(
            f"SELECT region FROM {Region.__table_name__}"
        ).fetchall()
    ]
    missing = [r.short() for r in provinces if r.short() not in db_regions]
    if missing:
        _handle(
            f"Regions {missing} are absent from the region table. "
            + "canoe-base must seed all regions before this module runs.",
            behavior,
        )


def check_missing_time_slices(
    db_conn: Connection,
    time_slices: CANOETimeSliceSet,
    behavior: Literal["error", "warning"] = "error",
):
    """
    Checks that every season and time-of-day value used by this module's DSD rows
    exists in the time_season and time_of_day tables respectively.
    """
    cursor = db_conn.cursor()

    db_seasons = [
        row[0]
        for row in cursor.execute(
            f"SELECT season FROM {TimeSeason.__table_name__}"
        ).fetchall()
    ]
    db_tods = [
        row[0]
        for row in cursor.execute(
            f"SELECT tod FROM {TimeOfDay.__table_name__}"
        ).fetchall()
    ]

    missing_seasons = np.unique(
        [s.season for s in time_slices.as_list() if s.season not in db_seasons]
    )
    missing_tods = np.unique(
        [t.tod for t in time_slices.as_list() if t.tod not in db_tods]
    )

    if len(missing_seasons) > 0:
        _handle(
            f"Seasons {missing_seasons} are absent from time_season. "
            + "canoe-base must seed all seasons before this module runs.",
            behavior,
        )
    if len(missing_tods) > 0:
        _handle(
            f"Time-of-day values {missing_tods} are absent from time_of_day. "
            + "canoe-base must seed all time-of-day entries before this module runs.",
            behavior,
        )


def check_emission_commodity(
    db_conn: Connection,
    EPA_emission_commodity: str,
    behavior: Literal["error", "warning"] = "error",
):
    """
    Checks that the emission commodity (e.g. CO2eq) exists in the commodity table.

    This commodity spans all sectors and is seeded by canoe-base. See DECISIONS.md — decision 2.
    """
    cursor = db_conn.cursor()
    row = cursor.execute(
        f"SELECT name FROM {Commodity.__table_name__} WHERE name = ?",
        (EPA_emission_commodity,),
    ).fetchone()
    if row is None:
        _handle(
            f"Emission commodity '{EPA_emission_commodity}' is absent from the commodity table. "
            + "canoe-base must seed this cross-sector commodity. See DECISIONS.md — decision 2.",
            behavior,
        )


def _handle(msg: str, behavior: Literal["error", "warning"]):
    if behavior == "error":
        raise ValueError(msg)
    else:
        logger.warning(msg)

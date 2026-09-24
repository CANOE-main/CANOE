"""
Checks of the canoe-base database shared by all sectors.

All functions here are read-only against the database. Each sector's `validation`
module combines the checks it needs to verify, before writing, that the database
contains the structure its config expects, and fails loudly (or warns) rather than
silently writing wrong data.
"""

from sqlite3 import Connection
from typing import Literal

import numpy as np
from canoe_schema.v4_0.models import (
    Commodity,
    Region,
    TimeOfDay,
    TimePeriod,
    TimeSeason,
)
from loguru import logger

from canoe.common.emissions import CANOEEmission
from canoe.common.naming import get_emission_commodity_name
from canoe.common.provinces import CANOEProvince
from canoe.common.time_slices import CANOETimeSliceSet

ValidationBehavior = Literal["error", "warning"]
"""What to do when a check fails: raise a `ValueError` or log a warning and go on."""


def check_missing_periods(
    db_conn: Connection,
    future_periods: list[int],
    behavior: ValidationBehavior = "error",
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
        handle_validation_issue(
            f"Future periods {missing} are absent from time_period (flag='f'). "
            + "canoe-base must seed all model periods before this module runs.",
            behavior,
        )


def check_missing_regions(
    db_conn: Connection,
    provinces: list[CANOEProvince],
    behavior: ValidationBehavior = "error",
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
        handle_validation_issue(
            f"Regions {missing} are absent from the region table. "
            + "canoe-base must seed all regions before this module runs.",
            behavior,
        )


def check_missing_time_slices(
    db_conn: Connection,
    time_slices: CANOETimeSliceSet,
    behavior: ValidationBehavior = "error",
):
    """
    Checks that every season and time-of-day value used by a module's DSD rows
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
        handle_validation_issue(
            f"Seasons {missing_seasons} are absent from time_season. "
            + "canoe-base must seed all seasons before this module runs.",
            behavior,
        )
    if len(missing_tods) > 0:
        handle_validation_issue(
            f"Time-of-day values {missing_tods} are absent from time_of_day. "
            + "canoe-base must seed all time-of-day entries before this module runs.",
            behavior,
        )


def check_emission_commodities(
    db_conn: Connection,
    behavior: ValidationBehavior = "error",
):
    """
    Checks that the emission commodities of every gas exist in the commodity table.

    These commodities span all sectors and are registered by the central emissions
    step (`canoe.emissions.processing.init`) before the modules run.
    """
    cursor = db_conn.cursor()
    db_commodities = {
        row[0]
        for row in cursor.execute(
            f"SELECT name FROM {Commodity.__table_name__}"
        ).fetchall()
    }
    missing = [
        get_emission_commodity_name(emission)
        for emission in CANOEEmission
        if get_emission_commodity_name(emission) not in db_commodities
    ]
    if missing:
        handle_validation_issue(
            f"Emission commodities {missing} are absent from the commodity table. "
            + "The central emissions step must register them before this module runs.",
            behavior,
        )


def handle_validation_issue(msg: str, behavior: ValidationBehavior):
    """Raise `ValueError(msg)` or log it as a warning, depending on `behavior`."""
    if behavior == "error":
        raise ValueError(msg)
    else:
        logger.warning(msg)

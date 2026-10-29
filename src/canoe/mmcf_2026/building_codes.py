"""
Building codes: shell efficiency, so the space heating and cooling demands of the
residential and commercial sectors fall linearly from the base year to the end year
(CER Canada Net-zero: residential 50%, commercial 43%).
"""

import sqlite3

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from canoe.common import CANOESector, naming

_MARKER = "building code shell efficiency"


class BuildingCodesConfig(BaseModel):
    """Building codes, `[compiler.mmcf2026.building_codes]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    base_year: int = 2025
    """Year the demands are unchanged."""

    end_year: int = 2050
    """Year the demands have fallen by the full reduction."""

    residential_reduction: float = Field(default=0.50, ge=0, le=1)
    """Share of the residential space heating and cooling demand saved at `end_year`."""

    commercial_reduction: float = Field(default=0.43, ge=0, le=1)
    """Share of the commercial space heating and cooling demand saved at `end_year`."""


def apply(conn: sqlite3.Connection, config: BuildingCodesConfig) -> None:
    reductions = {
        (CANOESector.Residential, "SPH"): config.residential_reduction,
        (CANOESector.Residential, "SPC"): config.residential_reduction,
        (CANOESector.Commercial, "SPH"): config.commercial_reduction,
        (CANOESector.Commercial, "SPC"): config.commercial_reduction,
    }
    span = config.end_year - config.base_year

    for (sector, end_use), reduction in reductions.items():
        commodity = naming.get_commodity_name(sector, end_use, is_demand=True)
        periods = conn.execute(
            "SELECT DISTINCT period FROM demand WHERE commodity = ? AND period > ?",
            (commodity, config.base_year),
        ).fetchall()
        if not periods:
            logger.warning(f"Building codes: no {commodity} demand to reduce")
        for (period,) in periods:
            factor = 1 - reduction * (period - config.base_year) / span
            # The marker keeps a rerun from reducing the demand twice
            conn.execute(
                """
                UPDATE demand
                SET demand = demand * ?, notes = COALESCE(notes || '; ', '') || ?
                WHERE commodity = ? AND period = ? AND COALESCE(notes, '') NOT LIKE ?
                """,
                (factor, _MARKER, commodity, period, f"%{_MARKER}%"),
            )

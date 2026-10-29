"""
Coal power phaseout: the existing coal generators retire, and their activity is
limited to zero in every region from the phaseout year.
"""

import sqlite3

from pydantic import BaseModel, ConfigDict

from canoe.common.naming import DatasetIdentifier


class CoalPhaseoutConfig(BaseModel):
    """Coal power phaseout, `[compiler.mmcf2026.coal_phaseout]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    phaseout_year: int = 2030
    """First period with no coal generation."""

    tech: str = "E_COAL-EXS"
    """Technology phased out."""


def apply(
    conn: sqlite3.Connection,
    config: CoalPhaseoutConfig,
    periods: list[int],
    data_id: DatasetIdentifier,
) -> None:
    conn.execute("UPDATE technology SET retire = 1 WHERE tech = ?", (config.tech,))
    conn.executemany(
        """
        REPLACE INTO limit_activity(
            region, period, tech_or_group, operator, activity, units, notes, data_id
        )
        VALUES ('global', ?, ?, 'le', 0, 'PJ', 'Coal power phaseout', ?)
        """,
        [
            (period, config.tech, data_id.get_dataset_code())
            for period in periods
            if period >= config.phaseout_year
        ],
    )

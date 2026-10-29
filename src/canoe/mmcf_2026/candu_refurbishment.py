"""
CANDU refurbishment: the existing reactors shut down for a refurbishment at the end of
their life and then run for a life extension. Its cost is the Darlington refurbishment
cost per unit capacity (2016-2026, taken as roughly 2020 dollars) spread over the
years of the shutdown. Applies to Ontario.
"""

import sqlite3

from pydantic import BaseModel, ConfigDict, Field

from canoe.common.naming import DatasetIdentifier


class CANDURefurbishmentConfig(BaseModel):
    """CANDU refurbishment, `[compiler.mmcf2026.candu_refurbishment]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    tech: str = "E_NUC_CANDU-EXS"
    """Technology refurbished."""

    region: str = "ON"
    """Region of the refurbishments."""

    original_life: int = 60
    """Years from the vintage to the refurbishment."""

    shutdown_years: int = 3
    """Years the refurbished reactor is offline."""

    extension_years: int = 30
    """Years the reactor runs after the refurbishment."""

    fixed_cost: float = Field(default=177.983, ge=0)
    """Fixed cost of operation per unit capacity (M$/GW-year) in the refurbishment
    period."""

    refurbishment_cost: float = Field(default=728.929385, ge=0)
    """Refurbishment cost per unit capacity (M$/GW) in the refurbishment period."""

    pj_per_gw_year: float = Field(default=31.536, gt=0)
    """Generation of a gigawatt running all year, PJ."""


def apply(
    conn: sqlite3.Connection,
    config: CANDURefurbishmentConfig,
    periods: list[int],
    period_step: int,
    data_id: DatasetIdentifier,
) -> None:
    tech, region = config.tech, config.region
    life = config.original_life + config.shutdown_years + config.extension_years
    conn.execute("UPDATE lifetime_tech SET lifetime = ? WHERE tech = ?", (life, tech))

    # Extend the costs through the horizon from the last existing row of each vintage,
    # before the refurbishment cost is added so the copies carry the normal cost
    for table in ("cost_fixed", "cost_variable"):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        select_columns = ", ".join("?" if c == "period" else c for c in columns)
        last_rows = conn.execute(
            f"""
            SELECT region, vintage, max(period) FROM {table}
            WHERE tech = ? GROUP BY region, vintage
            """,
            (tech,),
        ).fetchall()
        for row_region, vintage, last_period in last_rows:
            for period in periods:
                if period <= last_period or period > vintage + life:
                    continue
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {table}({", ".join(columns)})
                    SELECT {select_columns} FROM {table}
                    WHERE tech = ? AND region = ? AND vintage = ? AND period = ?
                    """,
                    (period, tech, row_region, vintage, last_period),
                )

    conn.execute(
        "UPDATE cost_fixed SET cost = ? WHERE tech = ? AND period = vintage + ?",
        (
            config.fixed_cost + config.refurbishment_cost,
            tech,
            config.original_life,
        ),
    )

    total = conn.execute(
        "SELECT sum(capacity) FROM existing_capacity WHERE region = ? AND tech = ?",
        (region, tech),
    ).fetchone()[0]
    if not total:
        return

    offline_share = config.shutdown_years / period_step
    for period in periods:
        retiring = conn.execute(
            """
            SELECT sum(capacity) FROM existing_capacity
            WHERE region = ? AND tech = ? AND ? = vintage + ?
            """,
            (region, tech, period, config.original_life),
        ).fetchone()[0]
        if not retiring:
            continue
        # Generation allowed with the retiring units offline for the shutdown
        limit = (total - retiring * offline_share) * config.pj_per_gw_year
        conn.execute(
            """
            REPLACE INTO limit_activity(
                region, period, tech_or_group, operator, activity, units, notes, data_id
            )
            VALUES (?, ?, ?, 'le', ?, 'PJ', 'some units offline for refurbishment', ?)
            """,
            (region, period, tech, limit, data_id.get_dataset_code()),
        )

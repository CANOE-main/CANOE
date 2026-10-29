"""
Unit commitment of the thermal generators, CODERS generic data (unit sizes, minimum
output, minimum up and down times, start-up costs) for the Temoa `unit_commitment`
extension. Written for the generators the database has in each region.
"""

import sqlite3
from importlib.resources import files
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from canoe.common import CANOEProvince

_TABLES = """
CREATE TABLE IF NOT EXISTS unit_commitment
(
    region               TEXT    NOT NULL,
    tech                 TEXT    NOT NULL,
    unit_capacity        REAL    NOT NULL,
    min_output_fraction  REAL    NOT NULL DEFAULT 0.0,
    max_output_fraction  REAL    NOT NULL DEFAULT 1.0,
    min_up_time_hours    INTEGER NOT NULL DEFAULT 0,
    min_down_time_hours  INTEGER NOT NULL DEFAULT 0,
    linearized           INTEGER NOT NULL DEFAULT 0,
    units                TEXT,
    notes                TEXT,
    CHECK (unit_capacity > 0),
    CHECK (0 <= min_output_fraction AND min_output_fraction <= 1),
    CHECK (0 < max_output_fraction AND max_output_fraction <= 1),
    CHECK (min_output_fraction <= max_output_fraction),
    CHECK (min_up_time_hours >= 0),
    CHECK (min_down_time_hours >= 0),
    CHECK (linearized IN (0, 1)),
    PRIMARY KEY (region, tech)
);
CREATE TABLE IF NOT EXISTS unit_commitment_startup_cost
(
    region         TEXT NOT NULL,
    tech           TEXT NOT NULL,
    cost_per_cap   REAL NOT NULL,
    units          TEXT,
    notes          TEXT,
    CHECK (cost_per_cap > 0),
    PRIMARY KEY (region, tech)
);
CREATE TABLE IF NOT EXISTS unit_commitment_startup_emissions
(
    region         TEXT NOT NULL,
    emis_comm      TEXT NOT NULL,
    tech           TEXT NOT NULL,
    emis_per_cap   REAL NOT NULL,
    units          TEXT,
    notes          TEXT,
    CHECK (emis_per_cap > 0),
    PRIMARY KEY (region, emis_comm, tech)
);
CREATE TABLE IF NOT EXISTS unit_commitment_startup_input
(
    region         TEXT NOT NULL,
    input_comm     TEXT NOT NULL,
    tech           TEXT NOT NULL,
    input_per_cap  REAL NOT NULL,
    units          TEXT,
    notes          TEXT,
    CHECK (input_per_cap > 0),
    PRIMARY KEY (region, input_comm, tech)
);
CREATE TABLE IF NOT EXISTS output_unit_commitment
(
    scenario    TEXT,
    region      TEXT,
    sector      TEXT REFERENCES sector_label (sector),
    period      INTEGER REFERENCES time_period (period),
    season      TEXT REFERENCES time_season (season),
    tod         TEXT REFERENCES time_of_day (tod),
    tech        TEXT REFERENCES technology_label (tech),
    vintage     INTEGER REFERENCES time_period (period),
    online_cap  REAL,
    start_cap   REAL,
    stop_cap    REAL,
    units       TEXT,
    PRIMARY KEY (scenario, region, sector, period, season, tod, tech, vintage)
);
"""

_UNIT_COLUMNS = [
    "tech",
    "unit_capacity",
    "min_output_fraction",
    "max_output_fraction",
    "min_up_time_hours",
    "min_down_time_hours",
    "linearized",
    "notes",
]


class UnitCommitmentConfig(BaseModel):
    """Unit commitment, `[compiler.mmcf2026.unit_commitment]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    data_file: Path | None = None
    """CSV of the generators' unit commitment data, with the columns of the packaged
    one (`data/unit_commitment.csv`, CODERS generic data), used if left out."""


def apply(
    conn: sqlite3.Connection,
    config: UnitCommitmentConfig,
    provinces: list[CANOEProvince],
) -> None:
    # Not executescript, which commits the surrounding transaction
    for statement in filter(str.strip, _TABLES.split(";")):
        conn.execute(statement)

    if config.data_file is not None:
        data = pd.read_csv(config.data_file)
    else:
        with files("canoe.mmcf_2026").joinpath("data/unit_commitment.csv").open(
            "rb"
        ) as f:
            data = pd.read_csv(f)

    units = data[_UNIT_COLUMNS].assign(units="GW")
    costs = data[["tech", "cost_per_cap", "notes"]].assign(units="M$/GW")
    for province in provinces:
        region = province.short()
        conn.executemany(
            """
            INSERT OR REPLACE INTO unit_commitment(
                tech, unit_capacity, min_output_fraction, max_output_fraction,
                min_up_time_hours, min_down_time_hours, linearized, notes, units, region
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(*row, region) for row in units.itertuples(index=False, name=None)],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO unit_commitment_startup_cost(
                tech, cost_per_cap, notes, units, region
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [(*row, region) for row in costs.itertuples(index=False, name=None)],
        )

    # Technologies the database does not have in a region
    for table in ("unit_commitment", "unit_commitment_startup_cost"):
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE (region, tech) NOT IN (SELECT region, tech FROM efficiency)
            """
        )

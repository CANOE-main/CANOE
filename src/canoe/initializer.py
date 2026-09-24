"""
Build a base database that contains the definitions for:
- Region
- TimeOfDay
- TimePeriod
- TimeSeason
"""

import argparse
import sqlite3
import tomllib
from pathlib import Path

from canoe_schema.sql import get_sql_schema
from canoe_schema.v4_0.enums import (
    TimePeriodTypeCode,
)
from canoe_schema.v4_0.models import (
    MetadataReal,
    Region,
    TimeOfDay,
    TimePeriod,
    TimeSeason,
)
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import CANOEProvince, GoldConnectorConfig
from .common.gdp import CERScenario, GDPProjectionPoint
from .emissions import EmissionsConfig


class CANOEBaseConfig(BaseModel):
    """
    Settings shared by the whole model, `[compiler.base]` in the pipeline TOML.

    Sector configs inherit the fields they declare with `inherit()` (see
    `canoe.common.module_inheritance`) unless their own TOML sets them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    # TODO currently schema import for pydantic objects is hard-coded
    db_output_dir: Path
    """Path of the output database. Rebuilt from scratch on every run."""

    data_version: str
    """Version in the data set codes (e.g. COMHR003), inherited by the modules."""

    existing_periods: list[int]
    """Existing (past) periods, written to `time_period` with flag 'e'."""

    future_periods: list[int]
    """Temoa's `time_future`: the model periods followed by the end of the horizon,
    e.g. [2025, ..., 2045, 2050] has model periods 2025-2045, the last one ending in
    2050."""

    provinces: list[CANOEProvince]
    """Regions of the model."""

    global_discount_rate: float = 0.03
    """Used for `global_discount_rate` and for `default_loan_rate`."""

    emissions: EmissionsConfig = Field(default_factory=EmissionsConfig)
    """Emission commodities, GWPs and costs, see `canoe.emissions`."""

    data_cache_config: GoldConnectorConfig
    """Location and date of the data lake cache."""

    gdp_scenario: CERScenario = CERScenario.GlobalNetZero
    """CER scenario of the GDP projections that scale the sector demands."""

    gdp_projection_point: GDPProjectionPoint = GDPProjectionPoint.PeriodEnd
    """Year of each model period at which projected GDP scales the base-year
    demands."""

    @classmethod
    def validate_from_toml(cls, toml_dir: str):
        with Path(toml_dir).open("rb") as f:
            return cls.model_validate(tomllib.load(f))

    @field_validator("db_output_dir")
    @classmethod
    def expand_path(cls, v: Path) -> Path:
        return v.expanduser()


def time_related_values(config: CANOEBaseConfig, db_cursor: sqlite3.Cursor):
    """
    Apply the time-related values to an existing database

    Writes: TimeOfDay, TimePeriod (present and future), TimeSeason
    """
    # Precompute sequence-label pairs e.g. (8, "H08")
    tod_sequence = [(t, f"H{t:02d}") for t in range(1, 25)]
    time_season_sequence = [(d - 1, f"D{d:03d}") for d in range(1, 366)]

    # Insert time of day
    _ = db_cursor.executemany(
        *TimeOfDay.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [TimeOfDay(sequence=i, tod=t, hours=1) for i, t in tod_sequence]
        )
    )

    # Insert Periods
    _ = db_cursor.executemany(
        *TimePeriod.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [
                TimePeriod(sequence=None, period=t, flag=TimePeriodTypeCode.E)
                for t in config.existing_periods
            ],
            include_nulls=True,
        )
    )

    _ = db_cursor.executemany(
        *TimePeriod.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [
                TimePeriod(sequence=i, period=t, flag=TimePeriodTypeCode.F)
                for i, t in enumerate(config.future_periods)
            ]
        )
    )

    # Insert seasons
    _ = db_cursor.executemany(
        *TimeSeason.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [
                TimeSeason(
                    sequence=i,
                    season=season,
                    segment_fraction=float(1 / 365),
                    notes="",
                )
                for (i, season) in time_season_sequence
            ]
        )
    )


def global_parameters(config: CANOEBaseConfig, db_cursor: sqlite3.Cursor):
    """
    Apply global parameters to an existing database

    Writes global_discount_rate and default_loan_rate. (Emission costs are written by
    the central emissions step, `canoe.emissions.processing.init`.)
    """
    db_cursor.execute(
        *MetadataReal(  # pyright: ignore[reportArgumentType]
            element="global_discount_rate", value=config.global_discount_rate
        ).to_update_sql()
    )

    db_cursor.execute(
        *MetadataReal(  # pyright: ignore[reportArgumentType]
            element="default_loan_rate", value=config.global_discount_rate
        ).to_update_sql()
    )


def prepare_database(db_path: Path, schema_sql: str) -> Path:
    """
    Builds an empty database and returns the final path
    """
    # Validate parent dir and remove if already exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
        logger.warning(f"Removed existing DB: {db_path}")

    # Create and identify tables
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        ]
    logger.debug(f"Prepared new DB with {len(tables)} tables")
    return db_path


def run(config: CANOEBaseConfig) -> None:
    """
    Initializes the CANOE database with the given configuration.
    NOTE: Hard-coded to schema version 4.0.
    """
    # Create empty database
    db_path = prepare_database(config.db_output_dir, get_sql_schema("4.0"))
    db_conn = sqlite3.connect(db_path)
    db_cursor = db_conn.cursor()

    # Fill regions
    region_sql, region_params = Region.to_bulk_insert_sql(
        [Region(region=province.short(), notes="") for province in config.provinces]
    )
    db_cursor.executemany(region_sql, region_params)

    # Time-related values
    time_related_values(config, db_cursor)

    # Global parameters
    global_parameters(config, db_cursor)

    # Close db
    db_conn.commit()
    db_conn.close()


def main(argv: list[str] | None = None) -> None:
    """argv=None → reads sys.argv (standalone mode). argv=[...] → used by Typer wrapper."""
    parser = argparse.ArgumentParser(
        prog="canoe-base",
        description="Build a base CANOE database that other modules will expand",
        epilog="Example:\n  build --cfg my_config.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cfg", required=True, help="Path to the configuration file")
    args = parser.parse_args(argv)

    # Parse config
    config = CANOEBaseConfig.validate_from_toml(args.cfg)
    run(config)


if __name__ == "__main__":
    main()

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
    CostEmission,
    MetadataReal,
    Region,
    TimeOfDay,
    TimePeriod,
    TimeSeason,
)
from loguru import logger
from pydantic import BaseModel, field_validator

from .common import CANOEProvince, GoldConnectorConfig


class EmissionsConfig(BaseModel):
    # Cost of CO2 in USD per ktCO2
    global_cost_of_co2: float = 0
    co2_commodity_name: str = "co2"
    emissions_units: str = "ktCO2"


class CANOEBaseConfig(BaseModel):
    # TODO currently schema import for pydantic objects is hard-coded
    db_output_dir: Path
    existing_periods: list[int]
    future_periods: list[int]
    provinces: list[CANOEProvince]
    # This is used for global_discount_rate and for default_loan_rate
    global_discount_rate: float = 0.03
    # TODO: Move to the module output section
    emissions: EmissionsConfig | None = None
    data_cache_config: GoldConnectorConfig

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

    Writes global_discount_rate, default_loan_rate, and CostEmission (if provided).
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

    if config.emissions is not None:
        # Global cost of CO2
        cost_emissions: list[CostEmission] = []
        for province, period in zip(config.provinces, config.future_periods):
            cost_emissions.append(
                CostEmission(
                    region=province.short(),
                    period=period,
                    emis_comm=config.emissions.co2_commodity_name,
                    cost=config.emissions.global_cost_of_co2,
                    units="ktCO2",
                    data_id="CANOEHR003",  # TODO: This needs to be handled dynamically
                )
            )
        _ = db_cursor.executemany(*CostEmission.to_bulk_insert_sql(cost_emissions))  # pyright: ignore[reportArgumentType]


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

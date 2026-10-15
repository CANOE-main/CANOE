"""
Apply a clustering to a database: the reduced, representative-days database.

The input database is copied and the copy edited in place, so every table the
reduction does not touch comes over as it is, whatever the schema. Only the tables
that must change (seasons, their sequence, the season-indexed tables, the demands)
depend on the schema version: one `_reduce_v*` function per version, with its table
names hard-coded.
"""

import shutil
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from math import isclose
from pathlib import Path

import pandas as pd
from canoe_schema.v4_0.models import TimeSeason, TimeSeasonSequential
from loguru import logger

from canoe.common import atomic_transaction
from canoe.representative_periods.config import RepresentativePeriodsConfig
from canoe.representative_periods.mapping import RepresentativeSeasonMapping
from canoe.representative_periods.reduction import (
    representative_seasons,
    reweight_demand_distribution,
    sequential_seasons,
)


@dataclass(frozen=True)
class RepresentativePeriodsOutput:
    """The reduced database and the Temoa settings it needs."""

    db_path: Path
    """Path of the reduced database."""
    time_sequencing: str
    """Temoa's `time_sequencing` for the reduced database."""


def build_representative_periods(
    input_db: Path, output_dir: Path, config: RepresentativePeriodsConfig
) -> RepresentativePeriodsOutput:
    """
    Main function of the representative periods step.

    Writes a copy of `input_db` reduced to the representative seasons of the
    configured clustering, as `<output_dir>/<input name>_<N>d.sqlite`. The input
    database is only read.
    """
    logger.info(f"Reducing {input_db} to representative periods...")

    mapping = config.clustering.mapping()
    # Representatives always represent themselves: their number needs no database
    n_periods = len(set(mapping.representative_of.values()))
    output_db = output_dir / f"{input_db.stem}_{n_periods}d.sqlite"

    with atomic_transaction(input_db, force_foreign_keys=False) as conn:
        version = get_schema_version(conn)

    # In this part we decide which processing function we have to use based on the schema
    reduce: Callable[
        [sqlite3.Connection, RepresentativeSeasonMapping, RepresentativePeriodsConfig],
        str,
    ]
    match version:
        case (4, 0):
            reduce = _reduce_v4
        case _:
            raise ValueError(
                f"{input_db}: schema version {version[0]}.{version[1]} not supported"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_db, output_db)
    try:
        # Foreign keys off while editing; checked at the end, where a failure names
        # the table (e.g. a season table missing from the version function)
        with atomic_transaction(output_db, force_foreign_keys=False) as conn:
            time_sequencing = reduce(conn, mapping, config)
            check_foreign_keys(conn)
    except Exception:
        # Never leave a full copy behind that looks like a reduced database
        output_db.unlink()
        raise
    # Separate from the edits: VACUUM cannot run inside a transaction
    with atomic_transaction(output_db) as conn:
        conn.execute("VACUUM")

    logger.info(f"Wrote {output_db} ({n_periods} representative seasons)")
    return RepresentativePeriodsOutput(
        db_path=output_db, time_sequencing=time_sequencing
    )


def get_schema_version(conn: sqlite3.Connection) -> tuple[int, int]:
    """Major and minor schema version, from `metadata` (`DB_MAJOR`, `DB_MINOR`)."""
    try:
        rows = dict(
            conn.execute(
                "SELECT element, value FROM metadata "
                + "WHERE element IN ('DB_MAJOR', 'DB_MINOR')"
            ).fetchall()
        )
    except sqlite3.OperationalError as e:
        raise ValueError(f"No schema version in the database: {e}") from e
    if set(rows) != {"DB_MAJOR", "DB_MINOR"}:
        raise ValueError(f"No DB_MAJOR and DB_MINOR in metadata, found {rows}")
    return int(rows["DB_MAJOR"]), int(rows["DB_MINOR"])


def check_foreign_keys(conn: sqlite3.Connection) -> None:
    """Raise if any row references a missing row, naming the tables."""
    # Each failure is (table, rowid, parent table, foreign key index)
    counts = Counter(
        (table, parent)
        for table, _, parent, _ in conn.execute("PRAGMA foreign_key_check")
    )
    if counts:
        raise ValueError(
            "Rows referencing missing rows (table -> parent: rows):\n"
            + "\n".join(f"  {t} -> {p}: {n}" for (t, p), n in counts.items())
        )


def _reduce_v4(
    conn: sqlite3.Connection,
    mapping: RepresentativeSeasonMapping,
    config: RepresentativePeriodsConfig,
) -> str:
    """
    Reduce a schema v4.0 database to the representative seasons. Returns Temoa's
    `time_sequencing` (v4 reads `days_per_period` from the Temoa config).
    """
    # Load
    # ----
    # Seasons in chronological order, with their share of the year
    seasons = pd.read_sql_query(
        "SELECT season, segment_fraction FROM time_season ORDER BY sequence", conn
    )
    representatives = mapping.representatives(seasons["season"].tolist())
    unmapped = sorted(set(seasons["season"]) - set(mapping.representative_of))
    if unmapped:
        logger.warning(f"Seasons the clustering does not represent: {unmapped}")

    # Demand distribution of the representative seasons
    placeholders = ", ".join("?" for _ in representatives)
    dsd = pd.read_sql_query(
        "SELECT region, period, season, tod, demand_name, dsd "
        + f"FROM demand_specific_distribution WHERE season IN ({placeholders})",
        conn,
        params=representatives,
    )
    logger.debug(
        f"Loaded {len(seasons)} seasons ({len(representatives)} representatives), "
        + f"{len(dsd)} distribution rows of the representatives"
    )

    # Compute (the same in every version)
    # -------
    kept = representative_seasons(mapping, seasons)
    sequence = sequential_seasons(mapping, seasons)
    new_dsd, demand_scale = reweight_demand_distribution(
        dsd, kept, config.dsd_threshold
    )

    # Write
    # -----
    # Every table with a season column; one missing here fails the foreign key check
    for table in [
        "capacity_factor_process",
        "capacity_factor_tech",
        "demand_specific_distribution",
        "efficiency_variable",
        "limit_seasonal_capacity_factor",
        "limit_storage_level_fraction",
        "reserve_capacity_derate",
    ]:
        conn.execute(
            f"DELETE FROM {table} WHERE season NOT IN ({placeholders})",
            representatives,
        )
    # Results of a Temoa run on the input database, if any
    for (table,) in conn.execute(
        "SELECT name FROM sqlite_master "
        + "WHERE type = 'table' AND name LIKE 'output\\_%' ESCAPE '\\'"
    ).fetchall():
        conn.execute(f"DELETE FROM {table}")

    conn.execute("DELETE FROM time_season_sequential")
    conn.execute("DELETE FROM time_season")
    conn.executemany(
        *TimeSeason.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [
                TimeSeason(
                    sequence=i,
                    season=season,
                    segment_fraction=fraction,
                    notes=f"Represents {represented} seasons",
                )
                for i, (season, fraction, represented) in enumerate(
                    zip(kept["season"], kept["segment_fraction"], kept["represented"])
                )
            ]
        )
    )
    conn.executemany(
        *TimeSeasonSequential.to_bulk_insert_sql(  # pyright: ignore[reportArgumentType]
            [
                TimeSeasonSequential(
                    sequence=i,
                    seas_seq=seas_seq,
                    season=season,
                    segment_fraction=fraction,
                    notes="",
                )
                for i, (seas_seq, season, fraction) in enumerate(
                    zip(
                        sequence["seas_seq"],
                        sequence["season"],
                        sequence["segment_fraction"],
                    )
                )
            ]
        )
    )

    conn.executemany(
        "UPDATE demand_specific_distribution SET dsd = ? WHERE region = ? "
        + "AND period = ? AND season = ? AND tod = ? AND demand_name = ?",
        new_dsd[["dsd", "region", "period", "season", "tod", "demand_name"]].itertuples(
            index=False, name=None
        ),
    )
    if config.demand_preservation == "hourly":
        conn.executemany(
            "UPDATE demand SET demand = demand * ? "
            + "WHERE region = ? AND period = ? AND commodity = ?",
            demand_scale[["scale", "region", "period", "demand_name"]].itertuples(
                index=False, name=None
            ),
        )
    logger.debug(
        f"Kept {len(kept)} seasons in {len(sequence)} sequential runs; "
        + f"reweighted {len(new_dsd)} distribution rows of {len(demand_scale)} demands"
    )

    # Check
    # -----
    # What Temoa needs of the written tables: the seasons and their sequence each
    # cover the year, and every demand distribution sums to 1
    for table in ["time_season", "time_season_sequential"]:
        (total,) = conn.execute(f"SELECT SUM(segment_fraction) FROM {table}").fetchone()
        if not isclose(total, 1, abs_tol=1e-9):
            raise ValueError(f"Segment fractions of {table} sum to {total}, not 1")
    off = conn.execute(
        "SELECT region, period, demand_name, SUM(dsd) AS total "
        + "FROM demand_specific_distribution GROUP BY region, period, demand_name "
        + "HAVING ABS(total - 1) > 1e-9"
    ).fetchall()
    if off:
        raise ValueError(f"Demand distributions not summing to 1: {off[:10]}")

    # v4 reads days_per_period and time_sequencing from the Temoa config
    return "representative_periods"

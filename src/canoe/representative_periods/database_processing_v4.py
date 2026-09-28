"""
Aligns a Temoa database with representative days configured in days.csv
"""

import math
import os
import sqlite3
from pathlib import Path

import pandas as pd
from canoe_schema.sql import get_sql_schema
from loguru import logger

from canoe.representative_periods import utils
from canoe.representative_periods.config import RepresentativePeriodsConfig

# this_dir = os.path.realpath(os.path.dirname(__file__)) + "/"
# input_dir = this_dir + "input_sqlite/"
# output_dir = this_dir + "output_sqlite/"

schema = get_sql_schema("4.0")

df_period: pd.DataFrame
initialised = False

# Label / enum / definition tables. Copied over first (order doesn't matter,
# foreign keys are off while copying), but kept separate from the data tables below for clarity
index_tables = {
    "data_set",
    "data_source",
    "data_source_label",
    "commodity_type",
    "commodity_label",
    "commodity",
    "technology_type",
    "technology_label",
    "technology",
    "tech_group_label",
    "sector_label",
    "region",
    "time_period_type",
    "time_period",
    "operator",
    "data_quality_credibility",
    "data_quality_geography",
    "data_quality_structure",
    "data_quality_technology",
    "data_quality_time",
}

direct_copy_tables = {
    "capacity_credit",
    "capacity_to_activity",
    "construction_input",
    "cost_emission",
    "cost_fixed",
    "cost_invest",
    "cost_variable",
    "demand",
    "efficiency",
    "emission_activity",
    "emission_embodied",
    "emission_end_of_life",
    "end_of_life_output",
    "existing_capacity",
    "lifetime_process",
    "lifetime_survival_curve",
    "lifetime_tech",
    "limit_activity",
    "limit_activity_share",
    "limit_annual_capacity_factor",
    "limit_capacity",
    "limit_capacity_share",
    "limit_degrowth_capacity",
    "limit_degrowth_new_capacity",
    "limit_degrowth_new_capacity_delta",
    "limit_emission",
    "limit_growth_capacity",
    "limit_growth_new_capacity",
    "limit_growth_new_capacity_delta",
    "limit_new_capacity",
    "limit_new_capacity_share",
    "limit_resource",
    "limit_tech_input_split",
    "limit_tech_input_split_annual",
    "limit_tech_output_split",
    "limit_tech_output_split_annual",
    "linked_tech",
    "loan_lifetime_process",
    "loan_rate",
    "metadata_real",
    "planning_reserve_margin",
    "ramp_down_hourly",
    "ramp_up_hourly",
    "rps_requirement",
    "storage_duration",
    "tech_group",
    "tech_group_member",
}

# For season tables, only copy where the season is in the rep day set
season_tables = {
    "demand_specific_distribution",
    "capacity_factor_tech",
    "capacity_factor_process",
    "efficiency_variable",
    "limit_seasonal_capacity_factor",
    "limit_storage_level_fraction",
    "reserve_capacity_derate",
}


def init(config: RepresentativePeriodsConfig):
    global df_period, df_sequence, initialised
    if initialised:
        return

    df_period = pd.read_csv(config.data_dir / "periods.csv", index_col=0)

    df_sequence = pd.read_csv(config.data_dir / "sequence.csv", index_col=0)
    change_points = df_sequence["period"] != df_sequence["period"].shift()
    group_id = change_points.cumsum()
    collapsed = df_sequence.groupby(group_id, as_index=False).agg({"period": "first"})
    collapsed["count"] = df_sequence.groupby(group_id).size().values
    df_sequence = collapsed

    # Split e.g. D001-D003 into D001, D002, D003
    if config.disaggregate_multiday and config.days_per_period > 1:
        for period, wgt in df_period.iterrows():
            days = period_to_days(period)
            weight = wgt.iloc[0] / len(days)

            for day in days:
                df_period.loc[day, "weight"] = weight

            df_period = df_period.drop(period, axis="index")

    print("\nApplying the following periods to v4.0 databases:\n")
    print(df_period)

    initialised = True
    print("\nInitialised database processing.\n")


def process_all(
    db_path: Path, output_dir: Path, config: RepresentativePeriodsConfig
) -> Path:
    init(config)
    # databases = _get_sqlite_databases()
    # for database in databases:
    return process_database(db_path, output_dir, config)


def process_database(
    database: Path, output_dir: Path, config: RepresentativePeriodsConfig
):

    if _get_schema_version(database) != (4, 0):
        return

    init(config)

    print(f"Processing {database}...")

    if config.disaggregate_multiday:
        n_hours = 24
    else:
        n_hours = 24 * config.days_per_period

    if n_hours < 100:
        hours = [utils.stringify_hour(hour + 1) for hour in range(n_hours)]
    else:
        hours = [
            utils.stringify_day(hour + 1).replace("D", "H") for hour in range(n_hours)
        ]

    if config.days_per_period == 1 or config.disaggregate_multiday:
        return process_single_day_period(database, output_dir, config)
    elif config.days_per_period > 1:
        raise ValueError(
            "Multiday periods are not currently supported by Temoa. Turn on dissaggregate_multiday."
        )


def process_single_day_period(
    database: Path, output_dir: Path, config: RepresentativePeriodsConfig
):

    # out_file = output_dir / f"{database.name}_{len(hours)}h.sqlite"
    out_file = output_dir / (
        "".join(database.name.split(".")[:-1]) + f"_{len(df_period)}d.sqlite"
    )
    logger.warning(out_file)
    # Check if database exists or needs to be built
    build_db = not os.path.exists(out_file)

    # Connect to the new database file
    conn = sqlite3.connect(out_file)
    curs = conn.cursor()  # Cursor object interacts with the sqlite db

    # Build the database if it doesn't exist. Otherwise clear all data if forced
    if build_db:
        curs.executescript(schema)
    else:
        tables = [
            t[0]
            for t in curs.execute(
                """SELECT name FROM sqlite_master WHERE type='table';"""
            ).fetchall()
        ]
        for table in tables:
            curs.execute(f"DELETE FROM '{table}'")
        curs.executescript(schema)

    conn.commit()
    conn.execute(f"ATTACH DATABASE '{database}' AS dbin")  # Attach the input database
    conn.execute("PRAGMA foreign_keys = 0;")  # Turn off foreign keys while copying over

    in_tables = [
        t[0]
        for t in curs.execute(
            "SELECT name FROM dbin.sqlite_master WHERE type='table';"
        ).fetchall()
    ]

    for table in index_tables:
        if table not in in_tables:
            continue
        cols = str(
            [row[1] for row in curs.execute(f"PRAGMA table_info({table})").fetchall()]
        )[1:-1].replace("'", "")
        curs.execute(
            f"REPLACE INTO main.{table}({cols}) SELECT {cols} FROM dbin.{table}"
        )

    for table in direct_copy_tables:
        if table not in in_tables:
            continue  # might be a db variant without the table
        cols = str(
            [row[1] for row in curs.execute(f"PRAGMA table_info({table})").fetchall()]
        )[1:-1].replace("'", "")
        curs.execute(
            f"REPLACE INTO main.{table}({cols}) SELECT {cols} FROM dbin.{table}"
        )

    periods = tuple(df_period.index.unique())
    if len(periods) > 1:
        raise ValueError("Multiple periods found in selection")
    for table in season_tables:
        if table not in in_tables:
            continue  # might be a db variant without the table
        cols = str(
            [row[1] for row in curs.execute(f"PRAGMA table_info({table})").fetchall()]
        )[1:-1].replace("'", "")
        curs.execute(
            f"REPLACE INTO main.{table}({cols}) SELECT {cols} FROM dbin.{table} WHERE season IN ('{periods[0]}')"
        )

    total_days = df_period["weight"].sum()
    curs.execute(
        f"REPLACE INTO metadata VALUES('days_per_period', {total_days}, 'count of days in each period')"
    )

    # TimeOfDay
    for h in range(24):
        tod = f"H0{h + 1}" if h + 1 < 10 else f"H{h + 1}"
        curs.execute(
            f'REPLACE INTO time_of_day(sequence, tod, hours) VALUES({h + 1}, "{tod}", 1)'
        )

    # time_season no longer varies by model year - segment_fraction is the
    # representative period's share of the whole year
    for i, (period, weight) in enumerate(df_period.iterrows()):
        curs.execute(f"""REPLACE INTO
                    time_season(sequence, season, segment_fraction, notes)
                    VALUES({i}, '{period}', {weight.iloc[0] / total_days}, "Weight from clustering")""")

    # time_season_sequential reconstructs the original year from the clustering sequence
    total_year_days = df_sequence["count"].sum()
    for i, row in df_sequence.iterrows():
        zeros = math.floor(math.log10(len(df_sequence))) - (
            0 if i == 0 else math.floor(math.log10(i))
        )
        period_seq = f"S{'0' * zeros}{i}"
        curs.execute(f"""REPLACE INTO
                    time_season_sequential(sequence, seas_seq, season, segment_fraction, notes)
                    VALUES({i}, '{period_seq}', '{row["period"]}', {row["count"] / total_year_days}, 'Reconstructed original year from clustering')""")

    # DemandSpecificDistribution
    # This is renormalised to sum to 1 below
    for period, weight in df_period.iterrows():
        curs.execute(f"""UPDATE demand_specific_distribution
                    SET dsd = dsd * {weight.iloc[0]}
                    WHERE season == '{period}'""")

    # Renormalise DSD
    df_dsd = pd.read_sql_query("SELECT * FROM demand_specific_distribution", conn)
    df_dsd = df_dsd.groupby(["region", "period", "demand_name"])
    for rpd in df_dsd.groups:
        # Drop threshold lower percentile
        df = df_dsd.get_group(rpd).sort_values("dsd").reset_index()

        # This is a safety net for low numbers of clusters where you might catch
        # a day with zero demand throughout, which is not normalisable
        if df["dsd"].sum() == 0:
            print(
                f"There was no DSD remaining for demand {rpd}! "
                "Filling with flatline demand for now but different periods "
                "should be used!"
            )
            flatline_fill = 1 / len(df)
            df["dsd"] = flatline_fill
            curs.execute(
                f"""UPDATE demand_specific_distribution
                SET dsd = {flatline_fill}
                WHERE region = '{rpd[0]}'
                AND period = '{rpd[1]}'
                AND demand_name = '{rpd[2]}'"""
            )

        # Get a running proportion sum of DSD
        df["run_sum"] = df["dsd"].cumsum() / df["dsd"].sum()
        # Get the smallest DSD above thresh to zero out actual table
        thresh_dsd = df["dsd"].loc[df["run_sum"] < config.dsd_threshold].max()
        thresh_dsd += 1e-12  # Small buffer to avoid floating point issues

        # There might be nothing under the threshold if using few rep days
        if not pd.isna(thresh_dsd) and thresh_dsd < df["dsd"].max():
            # Set to zero where the proportion exceeds the threshold
            # If there are duplicate dsd values on the threshold these are all left in
            # This leaves everything in in the case of a flatline demand
            df["dsd"] = df["dsd"].where(df["dsd"] >= thresh_dsd, 0)

            curs.execute(
                f"""UPDATE demand_specific_distribution
                SET dsd = 0
                WHERE region = '{rpd[0]}'
                AND period = '{rpd[1]}'
                AND demand_name = '{rpd[2]}'
                AND dsd < {thresh_dsd}"""
            )

        # Renormalise
        total_dsd = df["dsd"].sum()
        curs.execute(f"""UPDATE demand_specific_distribution
                    SET dsd = dsd / {total_dsd}
                    WHERE region = '{rpd[0]}'
                    AND period = '{rpd[1]}'
                    AND demand_name = '{rpd[2]}'""")

        # If preserving absolute hourly values, adjust annual demand to sum of representative periods
        if config.demand_preservation == "hourly":
            curs.execute(f"""UPDATE demand SET demand = demand * {total_dsd}
                        WHERE region = '{rpd[0]}'
                        AND period = '{rpd[1]}'
                        AND commodity == '{rpd[2]}'""")

    conn.commit()

    conn.execute("VACUUM;")
    conn.commit()

    conn.execute("PRAGMA FOREIGN_KEYS=1;")
    try:
        data = conn.execute("PRAGMA FOREIGN_KEY_CHECK;").fetchall()
        if data:
            for row in data:
                print(f"{row}")
            print("(Table, Row ID, Reference Table, (fkid) )")
            print(f"The above foreign keys failed to validate for {out_file}")
    except sqlite3.OperationalError as e:
        print(
            f"Foreign keys failed on activation for {out_file}. Something may be wrong with the schema."
        )
        print(e)

    conn.close()
    return out_file


# Collects sqlite databases into a dictionary of form {name: path}
# def _get_sqlite_databases():

#     databases = []

#     for dirs in os.walk(input_dir):
#         files = dirs[2]

#         for file in files:
#             split = os.path.splitext(file)
#             if split[1] == ".sqlite":
#                 databases.append(split[0])

#     return databases


def _get_schema_version(database: Path):

    conn = sqlite3.connect(database)
    curs = conn.cursor()

    tables = {t[0] for t in curs.execute("SELECT name FROM sqlite_schema").fetchall()}
    if "metadata" not in tables:
        print(f"Could not get schema version for {database}. Skipped.")
        return 0

    mj_vers = curs.execute(
        "SELECT value FROM metadata WHERE element == 'DB_MAJOR'"
    ).fetchone()[0]
    mn_vers = curs.execute(
        "SELECT value FROM metadata WHERE element == 'DB_MINOR'"
    ).fetchone()[0]

    return mj_vers, mn_vers


def period_to_days(period: str):

    if "-" not in period:
        return period
    else:
        days = [utils.destringify_day(day) for day in period.split("-")]
        days = [utils.stringify_day(day) for day in range(days[0], days[1] + 1, 1)]
        return tuple(days)


# if __name__ == "__main__":
#     if len(sys.argv) <= 1:
#         process_all()
#     else:
#         process_database(sys.argv[1])
#         print("Finished.")

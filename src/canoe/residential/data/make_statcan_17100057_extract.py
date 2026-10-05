"""
Makes `statcan_17100057_extract.csv` from the StatCan Table 17-10-0057-01 file the
previous residential module cached (`statcan_17100057.csv`, 154 MB: every scenario,
gender and age group, columns REF_DATE, GEO, Projection scenario, Gender, Age group
and VALUE).

The extract keeps the rows `residential.loaders.get_statcan_population_projections`
uses (medium-growth scenario M1, all genders, all ages), unchanged and with the same
columns, so the loader reads it as it would read the full file.

Usage: python make_statcan_17100057_extract.py <path to statcan_17100057.csv>
"""

import sys
from pathlib import Path

import pandas as pd

SCENARIO = "Projection scenario M1: medium-growth"
GENDER = "Total - gender"
AGE_GROUP = "All ages"


def main(full_file: Path):
    df = pd.read_csv(full_file, index_col=0)
    extract = df[
        (df["Projection scenario"] == SCENARIO)
        & (df["Gender"] == GENDER)
        & (df["Age group"] == AGE_GROUP)
    ]
    extract.to_csv(Path(__file__).parent / "statcan_17100057_extract.csv")
    print(f"Kept {len(extract)} of {len(df)} rows")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

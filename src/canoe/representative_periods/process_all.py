"""
Runs clustering and processes all databased to selected representative periods
"""

import tomllib
from pathlib import Path

from matplotlib import pyplot as pp

from canoe.representative_periods.clustering import run as clustering
from canoe.representative_periods.config import RepresentativePeriodsConfig
from canoe.representative_periods.database_processing_v4 import (
    process_all as database_processing_v4,
)


def run_representative_periods(
    db_path: Path, output_dir: Path, config: RepresentativePeriodsConfig
) -> Path:
    clustering(config)
    out_file = database_processing_v4(db_path, output_dir, config)

    if config.show_plots:
        print("Showing plots.")
        pp.show()  # pyright: ignore[reportUnknownMemberType]
    return out_file


# Replace this with proper CLI
if __name__ == "__main__":
    with Path("configuration/representative-periods.toml").open("rb") as f:
        config = RepresentativePeriodsConfig.model_validate(tomllib.load(f))
    run_representative_periods(
        Path("canoe-pwd/canoe-v4-all-high.sqlite"), Path("canoe-pwd"), config
    )

from importlib.resources import files
from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common import GoldConnectorConfig


def get_comstock_map() -> pd.DataFrame:
    """Map from Comstock columns to end-use demands"""
    csv_resource = files("canoe.commercial").joinpath("config/comstock_map.csv")
    with csv_resource.open("rb") as f:
        return pd.read_csv(f)


def get_comstock_table(
    cache_config: GoldConnectorConfig,
    us_state: str,
    building_type: str,
    upgrade: str = "39",
) -> pd.DataFrame:
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_folder = cache_path / f"oedi_up{upgrade}_{us_state}_{building_type}"
    file_path = (
        file_folder
        / f"oedi_up{upgrade}_{us_state}_{building_type}_{cache_config.cache_date}.parquet"
    )
    logger.debug(f"Loading cached comstock table {us_state}-{building_type}-{upgrade}")
    return pd.read_parquet(file_path)  # pyright: ignore[reportUnknownMemberType]

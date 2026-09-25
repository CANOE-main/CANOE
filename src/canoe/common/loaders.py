"""
Loaders for cached datasets used by more than one sector.

Each function reads a single dataset of the data lake cache and is the only place that
knows its path and layout, so when the cache changes shape the error points to the
function to fix. Sector-specific datasets have their own loaders in each sector.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common.cache_connector import GoldConnectorConfig
from canoe.common.gdp import CERScenario


def get_cer_gdp(
    cache_config: GoldConnectorConfig,
    gdp_index_year: int,
    scenario: CERScenario = CERScenario.GlobalNetZero,
) -> pd.DataFrame:
    """
    Projected real GDP of Canada (CER Canada's Energy Future 2023 macro indicators).

    Parameters
    ----------
    cache_config : GoldConnectorConfig
        Location and date of the cache.
    gdp_index_year : int
        GDP is divided by its value in this year, the year of the base demand data it
        scales.
    scenario : CERScenario
        CER scenario.

    Returns
    -------
    pd.DataFrame
        GDP relative to `gdp_index_year`, by year (index) in column `gdp`.
    """
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_folder = cache_path / "cer_macro"
    file_path = file_folder / f"cer_macro_{cache_config.cache_date}.parquet"
    logger.debug(
        f"Loading cached gdp projections gdp_index_year={gdp_index_year} scenario={scenario}"
    )
    df = pd.read_parquet(file_path)
    df_gdp = (
        df[
            (df.Scenario == scenario.value)
            & (df.Variable == "Real Gross Domestic Product ($2012 Millions)")
        ][["Year", "Value"]]
        .rename({"Year": "year", "Value": "gdp"}, axis="columns")  # pyright: ignore[reportAttributeAccessIssue]
        .set_index("year")
    )

    return df_gdp / df_gdp.loc[gdp_index_year]

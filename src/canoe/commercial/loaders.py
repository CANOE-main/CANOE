from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince, GoldConnectorConfig


def get_comstock_map() -> pd.DataFrame:
    """Map from Comstock columns to end-use demands"""
    csv_resource = files("canoe.commercial").joinpath("config/comstock_map.csv")
    with csv_resource.open("rb") as f:
        return pd.read_csv(f)


def get_exchange_and_inflation_dfs() -> tuple[pd.DataFrame, pd.DataFrame]:
    exchange_resource = files("canoe.commercial").joinpath(
        "config/currency_exchange.csv"
    )
    with exchange_resource.open("rb") as f:
        exchange_df = pd.read_csv(f, index_col=0)

    inflation_resource = files("canoe.commercial").joinpath("config/cad_inflation.csv")
    with inflation_resource.open("rb") as f:
        inflation_df = pd.read_csv(f, index_col=0)
    return exchange_df, inflation_df


def get_aeo_data() -> pd.DataFrame:
    """Map from Comstock columns to end-use demands"""
    ktek_resource = files("canoe.commercial").joinpath("config/ktekx.xlsx")
    cdm_resource = files("canoe.commercial").joinpath("config/aeo_cdm_indexing.csv")
    with ktek_resource.open("rb") as f:
        ktek_df = pd.read_excel(
            f, sheet_name="ktek", skiprows=68, index_col=False
        ).iloc[1:, 0:27]
    with cdm_resource.open("rb") as f:
        cdm_idx = pd.read_csv(f, index_col=0)
        for col in ktek_df.columns:
            if col in cdm_idx.columns:
                ktek_df[col] = ktek_df[col].map(lambda n: cdm_idx.loc[n, col])  # pyright: ignore[reportUnknownLambdaType]  # noqa: B023
        ktek_df["techname"] = ktek_df["techname"].str.lower()
    return ktek_df


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
    return pd.read_parquet(file_path)


def get_usca_weather_map(
    cache_config: GoldConnectorConfig, province: "CANOEProvince"
) -> np.ndarray:
    """Loads the US-CA weather map from the cache."""
    cache_path = (
        cache_config.cache_dir
        / Path("silver")
        / cache_config.cache_date
        / Path(f"weather_maps_{province.short()}")
        / Path(f"weather_maps_{province.short()}_{cache_config.cache_date}.npz")
    )
    logger.debug(f"Loading cached weather map for {province}")
    return np.load(cache_path)["arr_0"]


def get_ceud_table(
    table_number: int,
    first_row: int,
    last_row: int,
    province: "CANOEProvince",
    cache_config: GoldConnectorConfig,
) -> pd.DataFrame:
    """Loads the CEUD table from the cache."""

    def _clean_row_label(s: str) -> str:
        """Strip digits 1-9 and non-alphanumeric chars (except punctuation) from NRCan row labels."""
        cleaned = "".join(c for c in s if c in "- /()–" or c.isalnum())
        return "".join(c for c in cleaned if c not in "123456789").lower()

    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = (
        cache_path
        / Path(f"nrcan_com_{province.get_nrcan_code()}_{table_number}")
        / Path(
            f"nrcan_com_{province.get_nrcan_code()}_{table_number}_{cache_config.cache_date}.parquet"
        )
    )
    df = pd.read_parquet(file_path)
    df = df.iloc[first_row : last_row + 1]
    df = df.drop("Unnamed: 2", axis=1, errors="ignore").set_index("Unnamed: 0").dropna()
    df.index.name = None
    df.index = [_clean_row_label(str(idx)) for idx in df.index]
    df.columns = [int(col) for col in df.columns]
    df = df.astype(float, errors="ignore")
    return df


def get_statcan_atlantic_fractions_table(
    data_cache_config: GoldConnectorConfig,
) -> pd.Series:
    """
    For the comprehensive energy use database in commercial, the atlantic provinces are all aggregated.
    To slice them up, we use energy proportions from Statcan data. The system scope of the Statcan
    data is different from NRCan, including upstream energy use, so we dont want to use it directly.
    """

    cache_path = (
        data_cache_config.cache_dir / Path("silver") / data_cache_config.cache_date
    )
    file_path = (
        cache_path
        / Path("statcan_25100029")
        / Path(f"statcan_25100029_{data_cache_config.cache_date}.csv")
    )

    df = pd.read_csv(file_path).fillna(0)

    df["region"] = df["GEO"].str.lower()
    df["fuel"] = df["Fuel type"].map(
        {  # pyright: ignore[reportArgumentType]
            "Primary electricity, hydro and nuclear": "electricity",
            "Total refined petroleum products": "oil",
            "Natural gas": "natural gas",
        }
    )
    df_fuel = df.groupby(["fuel"])["VALUE"].sum()

    for idx, row in df.iterrows():
        df.loc[idx, "fraction"] = row["VALUE"] / df_fuel.loc[row["fuel"]]  # pyright: ignore[reportAttributeAccessIssue]

    df = df.set_index(["region", "fuel"])["fraction"]
    return df  # pyright: ignore[reportReturnType]


def get_epa_emission_factors_table(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    US EPA GHG Emission Factors Hub, stationary combustion table, as cached: one row per
    fuel (`Fuel Type`) with `CO2 Factor` (kg/mmBtu), `CH4 Factor` and `N2O Factor`
    (g/mmBtu), plus section and unit header rows.
    """
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / "epa" / f"epa_{cache_config.cache_date}.parquet"
    logger.debug("Loading cached EPA emission factors")
    return pd.read_parquet(file_path)

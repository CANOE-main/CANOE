from functools import reduce
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince, GoldConnectorConfig

if TYPE_CHECKING:
    from .config import CANOECommercialConfig
from .loaders import get_comstock_map, get_comstock_table, get_usca_weather_map


def load_and_process_comstock(
    cfg: "CANOECommercialConfig",
) -> dict[CANOEProvince, pd.DataFrame]:
    """
    NREL Comstock is used for estimating DSD for each end use in each province.
    """
    # Pre-load all weather maps. It is too slow otherwise
    weather_maps = _load_all_weather_maps(cfg.provinces, cfg.data_cache_config)
    province_comstock = _load_provinces_comstock(cfg)

    province_dsd: dict[CANOEProvince, pd.DataFrame] = {}
    for province, comstock_df in province_comstock.items():
        province_df = pd.DataFrame()
        for end_use in cfg.end_uses:
            # All columns that match "{end_use} fuel"
            relevant_cols = [
                col for col in comstock_df.columns if end_use.get_full_name() in col
            ]
            # Normalize columns
            # TODO: We are assuming that the weather mapping is already available
            # Let's make sure the code to download and process the weather maps is accesible
            for column in relevant_cols:
                apply_mapping = cfg.comstock_config.apply_weather_mapping.get(
                    end_use, False
                )
                if apply_mapping:
                    logger.debug(
                        f"Applying US-CA weather map for {province}, {end_use}, {column}..."
                    )
                    comstock_df[column] = _apply_weather_mapping(
                        province, comstock_df[column], weather_maps
                    )
                else:
                    comstock_df[column] /= comstock_df[column].sum()

            # Aggregate across columns and then normalize
            eu_name = end_use.get_full_name()
            province_df[eu_name] = comstock_df[relevant_cols].sum(axis=1)
            province_df[eu_name] /= province_df[eu_name].sum()
        province_dsd[province] = province_df
    return province_dsd


def _apply_weather_mapping(
    province: CANOEProvince,
    comstock_df: pd.Series,
    weather_maps: dict[CANOEProvince, pd.DataFrame],
) -> pd.DataFrame:
    """
    Applies the US-CA weather mapping to the Comstock data for the given province.
    """
    weather_map = weather_maps[province]
    ca_data = pd.Series(np.matmul(weather_map, comstock_df)).interpolate(
        method="linear"
    )
    dsd = np.clip(ca_data, 0, np.inf)
    dsd = dsd / dsd.sum()
    return dsd


def _load_all_weather_maps(
    provinces: list[CANOEProvince],
    cache_config: "GoldConnectorConfig",
) -> dict[CANOEProvince, pd.DataFrame]:
    weather_maps: dict[CANOEProvince, pd.DataFrame] = {}
    for province in provinces:
        weather_map = get_usca_weather_map(cache_config, province)
        weather_maps[province] = weather_map
    return weather_maps


def _load_provinces_comstock(
    cfg: "CANOECommercialConfig",
) -> dict[CANOEProvince, pd.DataFrame]:
    # Comstock columns -> end use demand
    comstock_map = get_comstock_map()
    comstock_map.set_index(comstock_map.comstock_col, inplace=True)
    # Canadian province -> US state map
    us_map = cfg.comstock_config.us_map

    province_comstock_dfs: dict[CANOEProvince, pd.DataFrame] = {}
    for province in cfg.provinces:
        # Iterate over all the building types
        comstock_province_dfs: list[pd.DataFrame] = []
        for building in cfg.comstock_config.building_types:
            bldg_table = get_comstock_table(
                cfg.data_cache_config,
                us_state=us_map[province],
                building_type=building,
            )
            # Get the 00-hour first (starts from 15-min)
            bldg_table = bldg_table.iloc[list(range(-1, len(bldg_table) - 1))]

            table_dt = pd.to_datetime(bldg_table.timestamp)
            start_of_year = table_dt.dt.to_period("Y").dt.start_time
            delta = table_dt - start_of_year

            # Transform from 15-min resolution to hourly
            # averaging over the hour
            bldg_table["hour"] = (delta.dt.total_seconds() // 3600).astype(int)
            bldg_table = (
                bldg_table.groupby(["hour"]).mean(numeric_only=True).reset_index()
            )
            bldg_table.set_index("hour", inplace=True, drop=True)

            if (bldg_table.index != pd.RangeIndex(start=0, stop=8760)).any():
                raise ValueError(
                    "Invalid comstock dataframe: Index should be a RangeIndex from 0 to 8759"
                )

            comstock_province_dfs.append(bldg_table)

        # Add all the dataframes (across buildings)
        comstock_province_df: pd.DataFrame = reduce(
            lambda a, b: a.add(b, fill_value=0),
            comstock_province_dfs,
        )

        # Apply mapping
        # build the "old column -> new column" mapping from comstock_map
        mapping = (
            comstock_map["end_use"] + " " + comstock_map["fuel"]
        )  # index: com_col, values: euf_col

        # sum columns that map to the same euf_col
        grouped = comstock_province_df[mapping.index].T.groupby(mapping).sum().T
        province_comstock_dfs[province] = grouped
    return province_comstock_dfs

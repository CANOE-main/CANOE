from functools import reduce
from typing import TYPE_CHECKING

import pandas as pd

from canoe.common import CANOEProvince

if TYPE_CHECKING:
    from .config import CANOECommercialConfig
from .loaders import get_comstock_map, get_comstock_table


def load_and_process_comstock(cfg: "CANOECommercialConfig"):
    province_comstock = load_provinces_comstock(cfg)

    ...


def load_provinces_comstock(
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

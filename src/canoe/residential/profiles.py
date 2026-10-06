"""
Hourly profiles of the residential end uses (for the demand-specific distribution),
from NREL ResStock simulations of a comparable US state per province. Nothing in here
touches the database.
"""

import pandas as pd

from canoe.common import CANOEProvince, GoldConnectorConfig

from .loaders import get_resstock_consumption, resstock_housing_types


def load_resstock_consumption(
    resstock_us_states: dict[CANOEProvince, str],
    provinces: list[CANOEProvince],
    cache_config: GoldConnectorConfig,
) -> dict[tuple[str, str], pd.DataFrame]:
    """
    Hourly energy use per household of each ResStock housing type in the US states
    of `provinces`, each table read once (several provinces share a state).

    params:
    - resstock_us_states: US state whose profiles each province takes

    Returns (US state, NRCan building type, e.g. "apartments") -> hourly energy use
    by end use, see `loaders.get_resstock_consumption`
    """
    states = list(dict.fromkeys(resstock_us_states[p] for p in provinces))
    return {
        (state, building_type): get_resstock_consumption(
            cache_config, state, housing_type
        )
        for state in states
        for building_type, housing_type in resstock_housing_types().items()
    }

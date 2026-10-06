"""
Demand-specific distributions of the residential end uses: the hourly profile of
each demand in each province, from NREL ResStock simulations of a comparable US
state. Nothing in here touches the database.
"""

import numpy as np
import pandas as pd

from canoe.common import CANOEProvince
from canoe.common.time_slices import hour_to_day, hour_to_tod
from canoe.common.weather_maps import map_to_canadian_weather

from .end_uses import ResidentialEndUse


def demand_specific_distributions(
    resstock: dict[tuple[str, str], pd.DataFrame],
    household_shares: pd.DataFrame,
    resstock_us_states: dict[CANOEProvince, str],
    weather_maps: dict[CANOEProvince, np.ndarray],
    weather_mapping: dict[ResidentialEndUse, bool],
    provinces: list[CANOEProvince],
    tolerance: float,
) -> pd.DataFrame:
    """
    The hourly profile of each end use in each province, adding up to 1.

    The ResStock energy use per household of each NRCan building type in the
    province's US state, weighed by the province's share of households of that type
    (CEUD table 14); for end uses with `weather_mapping`, mapped from the state's
    weather to the province's (`canoe.common.weather_maps`). Hours below `tolerance`
    times the mean are set to 0 before normalising.

    params:
    - resstock: (US state, NRCan building type) -> hourly energy use by end use, see
      `profiles.load_resstock_consumption`
    - household_shares: columns `province`, `building_type`, `share`, CEUD table 14
    - resstock_us_states: US state of each province
    - weather_maps: weather map of each province whose profiles are mapped
    - weather_mapping: end uses modelled -> whether their profile is mapped

    Returns region, end_use, season, tod, dsd (8760 rows per region and end use)
    """
    hours = np.arange(8760)
    seasons = [hour_to_day(h) for h in hours]
    tods = [hour_to_tod(h) for h in hours]
    frames: list[pd.DataFrame] = []
    for province in provinces:
        state = resstock_us_states[province]
        shares = household_shares.loc[household_shares["province"].isin([province])]
        for end_use, mapped in weather_mapping.items():
            profile = sum(
                share * resstock[(state, building_type)][end_use].to_numpy()
                for building_type, share in zip(
                    shares["building_type"], shares["share"]
                )
            )
            profile = pd.Series(np.asarray(profile, dtype=float))
            if mapped:
                profile = map_to_canadian_weather(weather_maps[province], profile)
            profile = profile.where(profile >= profile.mean() * tolerance, 0.0)
            frames.append(
                pd.DataFrame(
                    {
                        "region": province,
                        "end_use": end_use,
                        "season": seasons,
                        "tod": tods,
                        "dsd": (profile / profile.sum()).to_numpy(),
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)

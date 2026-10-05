"""
Mapping of hourly US profiles to Canadian weather, shared by the buildings sectors.

The hourly profiles of the buildings sectors come from US simulations (NREL ComStock,
ResStock) of a comparable state. A weather map (see
`canoe.common.loaders.get_usca_weather_map`) replaces each hour of the province's
year with the mean of the US hours of matching temperature and humidity, so heating
and cooling follow the province's weather.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from canoe.common.cache_connector import GoldConnectorConfig
from canoe.common.loaders import get_usca_weather_map
from canoe.common.provinces import CANOEProvince


def load_weather_maps(
    provinces: list[CANOEProvince], cache_config: GoldConnectorConfig
) -> dict[CANOEProvince, np.ndarray]:
    """
    Weather map of each province, all loaded at once (each is 8760 x 8760; loading
    them one at a time where they are used is slow).

    The cached maps are in UTC; they are shifted 5 hours to EST, the time of the
    profiles. TODO: a patch for the silver layer.
    """
    return {
        province: np.roll(
            get_usca_weather_map(cache_config, province), shift=(-5, -5), axis=(0, 1)
        )
        for province in provinces
    }


def map_to_canadian_weather(
    weather_map: np.ndarray, us_profile: npt.ArrayLike
) -> pd.Series:
    """
    An hourly US profile (8760 values) mapped to a province's weather with its weather
    map. Hours with no matching US hour are interpolated linearly.
    """
    return pd.Series(np.matmul(weather_map, np.asarray(us_profile))).interpolate(
        method="linear"
    )

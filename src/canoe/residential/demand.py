"""
Projection of the residential demands from their base-year values. Nothing in here
touches the database.
"""

from enum import StrEnum

import pandas as pd


class DemandDriver(StrEnum):
    """Projected series that scales the base-year demands."""

    Population = "population"
    """The projected population (`population` of the base config; by province from
    StatCan by default), as the previous module."""

    GDP = "gdp"
    """The projected GDP (`gdp` of the base config; national from the CER by
    default), as the other sectors."""


def project_demand(base_demand: pd.DataFrame, growth: pd.DataFrame) -> pd.DataFrame:
    """
    The base-year demand of each region and end use times the region's growth to
    each model period.

    params:
    - base_demand: columns `region`, `end_use`, `demand` (CEUD data year)
    - growth: columns `region`, `period`, `growth`, see
      `canoe.common.projections.growth_by_period`

    Returns region, period, end_use, demand
    """
    projected = base_demand.merge(growth[["region", "period", "growth"]], on="region")
    return projected.assign(demand=projected["demand"] * projected["growth"]).reindex(
        columns=["region", "period", "end_use", "demand"]
    )

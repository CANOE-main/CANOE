"""
Projection of the residential demands from their base-year values. Nothing in here
touches the database.
"""

from enum import StrEnum

import pandas as pd

from canoe.common import CANOEProvince
from canoe.common.gdp import GDPProjectionPoint, projected_growth_by_period


class DemandDriver(StrEnum):
    """Projected series that scales the base-year demands."""

    Population = "population"
    """Provincial population (StatCan projections), as the previous module."""

    GDP = "gdp"
    """National GDP (CER Canada's Energy Future), as the other sectors."""


def population_by_year(
    estimates: pd.DataFrame,
    projections: pd.DataFrame,
    provinces: list[CANOEProvince],
) -> pd.DataFrame:
    """
    Population of each province by year, as the previous module put it together:
    the estimates (January 1st) up to their last year, then the province's
    projections (July 1st) after it, then, beyond the last projected year of the
    province, Canada's projected growth applied to the province.

    params:
    - estimates, projections: columns `geo` (StatCan name, "Canada" included),
      `year`, `population`; see `loaders.get_statcan_population_estimates` and
      `loaders.get_statcan_population_projections`

    Returns province, year, population

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> estimates = pd.DataFrame({"geo": "Ontario", "year": [2023, 2024], "population": [10.0, 11.0]})
    >>> projections = pd.DataFrame(
    ...     {
    ...         "geo": ["Ontario"] * 3 + ["Canada"] * 2,
    ...         "year": [2024, 2025, 2026, 2026, 2027],
    ...         "population": [10.5, 12.0, 13.0, 40.0, 44.0],
    ...     }
    ... )
    >>> population_by_year(estimates, projections, [ON])
      province  year  population
    0  Ontario  2023        10.0
    1  Ontario  2024        11.0
    2  Ontario  2025        12.0
    3  Ontario  2026        13.0
    4  Ontario  2027        14.3
    """

    def series(df: pd.DataFrame, geo: str) -> pd.Series:
        """Population of `geo` by year"""
        rows = df.loc[df["geo"] == geo]
        return pd.Series(rows["population"].to_numpy(), index=rows["year"].to_numpy())

    canada = series(projections, "Canada")
    frames: list[pd.DataFrame] = []
    for province in provinces:
        estimated = series(estimates, province.value)
        projected = series(projections, province.value)
        projected = projected.loc[projected.index > estimated.index.max()]
        last_year = int(projected.index.max())
        # Beyond the province's projections: Canada's growth from that year on
        growth = float(projected.loc[last_year]) / float(canada.loc[last_year])
        extended = canada.loc[canada.index > last_year] * growth
        population = pd.concat([estimated, projected, extended])
        frames.append(
            pd.DataFrame(
                {
                    "province": province,
                    "year": population.index,
                    "population": population.to_numpy(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def population_growth(
    population: pd.DataFrame,
    provinces: list[CANOEProvince],
    ceud_data_year: int,
    future_periods: list[int],
    period_step: int,
    projection_point: GDPProjectionPoint,
) -> pd.DataFrame:
    """
    Growth of each province's population from the CEUD data year to each model
    period (read at `projection_point`).

    params:
    - population: columns `province`, `year`, `population`, see `population_by_year`

    Returns region, period, growth

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> population = pd.DataFrame(
    ...     {"province": ON, "year": [2022, 2025, 2030, 2035], "population": [10.0, 11.0, 12.0, 13.0]}
    ... )
    >>> population_growth(population, [ON], 2022, [2025, 2030], 5, GDPProjectionPoint.PeriodEnd)
        region  period  growth
    0  Ontario    2025     1.2
    1  Ontario    2030     1.3
    """
    rows: list[tuple[CANOEProvince, int, float]] = []
    for province in provinces:
        # NOTE: enum columns are filtered with `isin` (pandas 3 `str` columns)
        own = population.loc[population["province"].isin([province])]
        series = pd.Series(own["population"].to_numpy(), index=own["year"].to_numpy())
        growth = projected_growth_by_period(
            series / float(series.loc[ceud_data_year]),
            future_periods,
            period_step,
            projection_point,
        )
        rows.extend((province, period, factor) for period, factor in growth.items())
    return pd.DataFrame(rows, columns=["region", "period", "growth"])


def gdp_growth(
    gdp_index: pd.DataFrame,
    provinces: list[CANOEProvince],
    future_periods: list[int],
    period_step: int,
    projection_point: GDPProjectionPoint,
) -> pd.DataFrame:
    """
    Growth of national GDP from the CEUD data year to each model period, the same in
    every province.

    params:
    - gdp_index: GDP relative to the CEUD data year, by year (index) in column `gdp`,
      see `canoe.common.loaders.get_cer_gdp`

    Returns region, period, growth
    """
    growth = projected_growth_by_period(
        gdp_index["gdp"], future_periods, period_step, projection_point
    )
    return pd.DataFrame(
        [
            (province, period, factor)
            for province in provinces
            for period, factor in growth.items()
        ],
        columns=["region", "period", "growth"],
    )


def project_demand(base_demand: pd.DataFrame, growth: pd.DataFrame) -> pd.DataFrame:
    """
    The base-year demand of each region and end use times the region's growth to
    each model period.

    params:
    - base_demand: columns `region`, `end_use`, `demand` (CEUD data year)
    - growth: columns `region`, `period`, `growth`, see `population_growth`

    Returns region, period, end_use, demand
    """
    projected = base_demand.merge(growth, on="region")
    return projected.assign(demand=projected["demand"] * projected["growth"]).reindex(
        columns=["region", "period", "end_use", "demand"]
    )

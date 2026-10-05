"""
Projection of the residential demands from their base-year values. Nothing in here
touches the database.
"""

from enum import StrEnum

import pandas as pd

from canoe.common import CANOEProvince


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

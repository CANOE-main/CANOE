"""
The existing generators: CODERS units grouped by region, technology and vintage.
"""

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince

from .catalogue import GenerationTechnology


def existing_generators(
    units: pd.DataFrame,
    provinces: list[CANOEProvince],
    lifetimes: dict[GenerationTechnology, int],
    first_period: int,
    period_step: int,
    threshold: float,
) -> pd.DataFrame:
    """
    Existing capacity of each technology by region and vintage.

    A unit's vintage is its last renewal (its start if never renewed), rounded to
    a multiple of `period_step` and at most the year before the first period; units
    of technologies that never retire (hydro) all take that year. Units built from
    the first period on are left out, and so are groups retired by the first period
    (vintage + lifetime) or with `threshold` GW or less.

    Parameters
    ----------
    units : pd.DataFrame
        CODERS generators, see `loaders.get_coders_generators`.
    provinces : list[CANOEProvince]
        Regions modelled; units elsewhere are left out.
    lifetimes : dict[GenerationTechnology, int]
        Lifetime of each technology, see `generation.parameters.existing_lifetimes`.
    first_period : int
        First model period.
    period_step : int
        Years between the vintages.
    threshold : float
        Smallest capacity kept, GW.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology` (`GenerationTechnology`), `vintage`,
        `capacity` (GW), `annual_energy` (average annual output, PJ) and
        `facilities` (names, ` - `-separated), sorted by technology, region and
        vintage.

    Examples
    --------
    A dam renewed in 2023 is a 2024 vintage, as all hydro; two Ontario gas turbines
    built in 2012 and 2013 fall in the 2010 and 2015 vintages:

    >>> ON = CANOEProvince.ONTARIO
    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON, ON],
    ...         "coders_type": ["ng_sc", "ng_sc", "hydro_daily"],
    ...         "facility": ["A", "B", "C"],
    ...         "capacity": [100.0, 50.0, 300.0],
    ...         "annual_energy": [200.0, 100.0, 1000.0],
    ...         "start_year": [2012, 2013, 1950],
    ...         "renewal_year": [2012, 2013, 2023],
    ...     }
    ... )
    >>> lifetimes = {
    ...     GenerationTechnology.NaturalGasCT: 45,
    ...     GenerationTechnology.HydroDaily: 100,
    ... }
    >>> fleet = existing_generators(units, [ON], lifetimes, 2025, 5, 0.001)
    >>> fleet[["technology", "vintage", "capacity", "facilities"]]
        technology  vintage  capacity facilities
    0  hydro_daily     2024      0.30          C
    1        ng_ct     2010      0.10          A
    2        ng_ct     2015      0.05          B
    """
    MW_TO_GW = 1e-3
    GWH_TO_PJ = 3.6e-3

    type_to_technology = {
        coders_type: technology
        for technology in GenerationTechnology
        for coders_type in technology.get_coders_fleet_types()
    }
    unmapped = sorted(set(units["coders_type"]) - set(type_to_technology))
    if unmapped:
        logger.warning(
            f"CODERS generator types {unmapped} have no technology and are left out"
        )

    fleet = units.loc[
        units["coders_type"].isin(list(type_to_technology))
        & units["region"].isin(provinces)
        & (units["capacity"] > 0)
    ].copy()
    fleet["technology"] = fleet["coders_type"].map(type_to_technology)

    built = fleet[["start_year", "renewal_year"]].max(axis=1)
    fleet = fleet.loc[built < first_period]
    built = built.loc[fleet.index]
    # Nearest multiple of the step (half up), at most the year before the first period
    rounded = (np.floor(built / period_step + 0.5) * period_step).astype(int)
    technologies: list[GenerationTechnology] = list(fleet["technology"])
    never_retires = pd.Series(
        [t.never_retires() for t in technologies], index=fleet.index
    )
    fleet["vintage"] = rounded.clip(upper=first_period - 1).mask(
        never_retires, first_period - 1
    )

    grouped = (
        fleet.groupby(["region", "technology", "vintage"], sort=False)
        .agg(
            capacity=("capacity", "sum"),
            annual_energy=("annual_energy", "sum"),
            facilities=("facility", " - ".join),
        )
        .reset_index()
    )
    grouped["capacity"] *= MW_TO_GW
    grouped["annual_energy"] *= GWH_TO_PJ

    missing = sorted(set(grouped["technology"]) - set(lifetimes))
    if missing:
        raise ValueError(f"Existing generators without a lifetime: {missing}")
    alive = grouped["vintage"] + grouped["technology"].map(lifetimes) > first_period
    grouped = grouped.loc[alive & (grouped["capacity"] > threshold)]

    # Catalogue order of technologies, then provinces, then vintages
    order = pd.DataFrame(
        {
            "technology": grouped["technology"].map(list(GenerationTechnology).index),
            "region": grouped["region"].map(list(CANOEProvince).index),
            "vintage": grouped["vintage"],
        }
    ).sort_values(["technology", "region", "vintage"])
    return grouped.loc[order.index].reset_index(drop=True)

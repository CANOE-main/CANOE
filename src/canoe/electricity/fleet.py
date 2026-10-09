"""
The existing generators and storage: CODERS units given a technology and a vintage
(`existing_units`, `existing_storage_units`), then grouped by region, technology and
vintage (`existing_generators`, `existing_storage`), with the same rules.
"""

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince

from .catalogue import GenerationTechnology, StorageTechnology


def existing_units(
    units: pd.DataFrame,
    provinces: list[CANOEProvince],
    first_period: int,
    period_step: int,
) -> pd.DataFrame:
    """
    The CODERS units of the modelled technologies and provinces, with their
    technology and vintage.

    A unit's vintage is its last renewal (its start if never renewed), rounded to
    a multiple of `period_step` and at most the year before the first period; units
    of technologies that never retire (hydro) all take that year. Units built from
    the first period on, and units without capacity, are left out.

    Parameters
    ----------
    units : pd.DataFrame
        CODERS generators, see `loaders.get_coders_generators`.
    provinces : list[CANOEProvince]
        Regions modelled; units elsewhere are left out.
    first_period : int
        First model period.
    period_step : int
        Years between the vintages.

    Returns
    -------
    pd.DataFrame
        The columns of `units` plus `technology` (`GenerationTechnology`) and
        `vintage`.

    Examples
    --------
    A dam renewed in 2023 is a 2024 vintage, as all hydro; gas turbines built in 2012
    and 2013 fall in the 2010 and 2015 vintages:

    >>> ON = CANOEProvince.ONTARIO
    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON, ON],
    ...         "coders_type": ["ng_sc", "ng_sc", "hydro_daily"],
    ...         "capacity": [100.0, 50.0, 300.0],
    ...         "start_year": [2012, 2013, 1950],
    ...         "renewal_year": [2012, 2013, 2023],
    ...     }
    ... )
    >>> existing_units(units, [ON], 2025, 5)[["technology", "vintage"]]
        technology  vintage
    0        ng_ct     2010
    1        ng_ct     2015
    2  hydro_daily     2024
    """
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
    return _with_vintages(fleet, first_period, period_step)


def existing_generators(
    units: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    first_period: int,
    threshold: float,
) -> pd.DataFrame:
    """
    Existing capacity of each technology by region and vintage: the units grouped,
    leaving out the groups retired by the first period (vintage + lifetime) or with
    `threshold` GW or less.

    Parameters
    ----------
    units : pd.DataFrame
        See `existing_units`.
    lifetimes : dict[GenerationTechnology, int]
        Lifetime of each technology, see `generation.parameters.generation_lifetimes`.
    first_period : int
        First model period.
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
    >>> ON = CANOEProvince.ONTARIO
    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON, ON],
    ...         "technology": [GenerationTechnology.NaturalGasCT] * 3,
    ...         "vintage": [1975, 2010, 2010],
    ...         "facility": ["A", "B", "C"],
    ...         "capacity": [100.0, 50.0, 30.0],
    ...         "annual_energy": [200.0, 100.0, 60.0],
    ...     }
    ... )
    >>> existing_generators(
    ...     units, {GenerationTechnology.NaturalGasCT: 45}, 2025, 0.001
    ... )[["vintage", "capacity", "facilities"]]
       vintage  capacity facilities
    0     2010      0.08      B - C
    """
    GWH_TO_PJ = 3.6e-3

    grouped = _grouped(
        units, lifetimes, first_period, threshold, list(GenerationTechnology),
        annual_energy=("annual_energy", "sum"),
    )  # fmt: skip
    grouped["annual_energy"] *= GWH_TO_PJ
    return grouped


def existing_storage_units(
    units: pd.DataFrame,
    provinces: list[CANOEProvince],
    first_period: int,
    period_step: int,
) -> pd.DataFrame:
    """
    The CODERS storage units of the modelled technologies and provinces, with their
    technology (by type and duration rounded to whole hours, half up) and vintage
    (as `existing_units`).

    Parameters
    ----------
    units : pd.DataFrame
        CODERS storage, see `loaders.get_coders_storage`.
    provinces : list[CANOEProvince]
        Regions modelled; units elsewhere are left out.
    first_period : int
        First model period.
    period_step : int
        Years between the vintages.

    Returns
    -------
    pd.DataFrame
        The columns of `units` plus `technology` (`StorageTechnology`) and `vintage`.

    Examples
    --------
    A 1.75-hour battery is a 2-hour one; a flywheel has no technology:

    >>> ON = CANOEProvince.ONTARIO
    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON],
    ...         "coders_type": ["storage_lithium", "storage_flywheel"],
    ...         "capacity": [20.0, 5.0],
    ...         "duration": [1.75, 0.1],
    ...         "start_year": [2020, 2016],
    ...         "renewal_year": [2020, 2016],
    ...     }
    ... )
    >>> existing_storage_units(units, [ON], 2025, 5)[["technology", "vintage"]]
       technology  vintage
    0  battery_2h     2020
    """
    type_to_technology = {
        (coders_type, technology.get_duration_hours()): technology
        for technology in StorageTechnology
        for coders_type in technology.get_coders_fleet_types()
    }
    hours = np.floor(units["duration"].to_numpy(dtype=float) + 0.5).astype(int)
    keys = [(str(t), int(h)) for t, h in zip(units["coders_type"], hours)]
    unmapped = sorted({key for key in keys if key not in type_to_technology})
    if unmapped:
        logger.warning(
            f"CODERS storage (type, hours) {unmapped} have no technology and are "
            + "left out"
        )
    mapped = pd.Series([key in type_to_technology for key in keys], index=units.index)
    fleet = units.loc[
        mapped & units["region"].isin(provinces) & (units["capacity"] > 0)
    ].copy()
    fleet["technology"] = [
        type_to_technology[(t, h)]
        for t, h in zip(
            fleet["coders_type"],
            np.floor(fleet["duration"].to_numpy(dtype=float) + 0.5).astype(int),
        )
    ]
    return _with_vintages(fleet, first_period, period_step)


def existing_storage(
    units: pd.DataFrame,
    lifetimes: dict[StorageTechnology, int],
    first_period: int,
    threshold: float,
) -> pd.DataFrame:
    """
    Existing capacity of each storage technology by region and vintage, grouped and
    filtered as `existing_generators`.

    Parameters
    ----------
    units : pd.DataFrame
        See `existing_storage_units`.
    lifetimes : dict[StorageTechnology, int]
        See `storage.parameters.storage_lifetimes`.
    first_period : int
        First model period.
    threshold : float
        Smallest capacity kept, GW.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology` (`StorageTechnology`), `vintage`, `capacity`
        (GW) and `facilities`, sorted by technology, region and vintage.
    """
    return _grouped(units, lifetimes, first_period, threshold, list(StorageTechnology))


def _with_vintages(
    fleet: pd.DataFrame, first_period: int, period_step: int
) -> pd.DataFrame:
    """
    `fleet` (with a `technology`) without the units built from the first period on,
    with their `vintage`: the last renewal (start if never renewed) rounded to a
    multiple of `period_step`, at most the year before the first period, which all
    the units of technologies that never retire take.
    """
    built = fleet[["start_year", "renewal_year"]].max(axis=1)
    fleet = fleet.loc[built < first_period].copy()
    built = built.loc[fleet.index]
    # Nearest multiple of the step (half up), at most the year before the first period
    rounded = (np.floor(built / period_step + 0.5) * period_step).astype(int)
    never_retires = pd.Series(
        [t.never_retires() for t in fleet["technology"]], index=fleet.index
    )
    fleet["vintage"] = rounded.clip(upper=first_period - 1).mask(
        never_retires, first_period - 1
    )
    return fleet.reset_index(drop=True)


def _grouped[T: (GenerationTechnology, StorageTechnology)](
    units: pd.DataFrame,
    lifetimes: dict[T, int],
    first_period: int,
    threshold: float,
    order: list[T],
    **sums: tuple[str, str],
) -> pd.DataFrame:
    """
    Units grouped by (region, technology, vintage), capacity in GW, without the
    groups retired by the first period or with `threshold` GW or less, in the order
    of `order` (technologies), provinces and vintages. `sums` are more columns to
    aggregate (pandas named aggregations).
    """
    MW_TO_GW = 1e-3

    grouped = (
        units.groupby(["region", "technology", "vintage"], sort=False)
        .agg(
            capacity=("capacity", "sum"),
            facilities=("facility", " - ".join),
            **sums,
        )
        .reset_index()
    )
    grouped["capacity"] *= MW_TO_GW

    missing = sorted(set(grouped["technology"]) - set(lifetimes))
    if missing:
        raise ValueError(f"Existing capacity without a lifetime: {missing}")
    lifetime = pd.Series(
        [lifetimes[t] for t in grouped["technology"]], index=grouped.index
    )
    alive = grouped["vintage"] + lifetime > first_period
    grouped = grouped.loc[alive & (grouped["capacity"] > threshold)]

    # Catalogue order of technologies, then provinces, then vintages
    sort_keys = pd.DataFrame(
        {
            "technology": [order.index(t) for t in grouped["technology"]],
            "region": [list(CANOEProvince).index(r) for r in grouped["region"]],
            "vintage": grouped["vintage"],
        },
        index=grouped.index,
    ).sort_values(["technology", "region", "vintage"])
    return grouped.loc[sort_keys.index].reset_index(drop=True)

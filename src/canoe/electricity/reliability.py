"""
Reliability parameters: the planning reserve margin of each province and what counts
towards it, plus the ramp rates of the thermal generators.

Temoa's `reserve_margin` setting picks how capacity counts towards the margin:
capacity credits (static: a share of each process's capacity, by period) or reserve
capacity derates (dynamic: a share of each process's available output, by season).
Both come from the same ratio, Ontario's capability at the summer peak over its
installed capacity, by fuel (IESO Reliability Outlook), applied to every province
(see `ELECTRICITY_MODULE_BUGS.md`, entry 3). The new wind and solar bins take their
capacity credits from the cached bins.

Storage, the CCS retrofits and the bypasses get none: Temoa's defaults apply (no
capacity credit, a derate of 1).
"""

import pandas as pd

from canoe.common import CANOEProvince

from .catalogue import GenerationTechnology


def ieso_capacity_ratios(
    capability: pd.DataFrame, peak_type: str
) -> dict[GenerationTechnology, float]:
    """
    Share of each technology's capacity available at the summer peak: the IESO
    capability (`peak_type`) of its fuel type over the installed capacity.
    Technologies without an IESO fuel type (see
    `GenerationTechnology.get_ieso_fuel_type`) are left out.

    Parameters
    ----------
    capability : pd.DataFrame
        See `loaders.get_ieso_summer_peak_capability`.
    peak_type : str
        `Firm` or `Planned`.

    Examples
    --------
    >>> capability = pd.DataFrame(
    ...     {"fuel_type": ["nuclear", "wind"], "installed": [100.0, 50.0],
    ...      "Firm": [80.0, 5.0], "Planned": [90.0, 5.0]}
    ... )
    >>> ratios = ieso_capacity_ratios(capability, "Firm")
    >>> ratios[GenerationTechnology.NuclearCANDU], ratios[GenerationTechnology.WindOnshore]
    (0.8, 0.1)
    >>> GenerationTechnology.Coal in ratios  # no gas/oil row
    False
    """
    by_fuel = dict(
        zip(capability["fuel_type"], capability[peak_type] / capability["installed"])
    )
    return {
        technology: float(by_fuel[fuel_type])
        for technology in GenerationTechnology
        if (fuel_type := technology.get_ieso_fuel_type()) in by_fuel
    }


def process_capacity_credits(
    processes: pd.DataFrame,
    ratios: dict[GenerationTechnology, float],
    lifetimes: dict[GenerationTechnology, int],
    periods: list[int],
) -> pd.DataFrame:
    """
    Capacity credit (static reserve margin) of each process in the periods its
    vintage lives: the IESO ratio of its technology.

    Parameters
    ----------
    processes : pd.DataFrame
        Generators (not the bins), see `generation.parameters.existing_processes`
        and `new_processes`.
    ratios : dict[GenerationTechnology, float]
        See `ieso_capacity_ratios`; technologies without one get no credit.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.
    periods : list[int]
        Model periods.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage`, `period` and `credit`.

    Examples
    --------
    >>> processes = pd.DataFrame(
    ...     {"region": [CANOEProvince.ONTARIO], "technology": [GenerationTechnology.Coal],
    ...      "vintage": [2000]}
    ... )
    >>> process_capacity_credits(
    ...     processes, {GenerationTechnology.Coal: 0.86}, {GenerationTechnology.Coal: 30},
    ...     [2025, 2030, 2035],
    ... )[["vintage", "period", "credit"]]
       vintage  period  credit
    0     2000    2025    0.86
    """
    rows = [
        {
            "region": region,
            "technology": technology,
            "vintage": vintage,
            "period": period,
            "credit": ratios[technology],
        }
        for region, technology, vintage in zip(
            processes["region"], processes["technology"], processes["vintage"]
        )
        if technology in ratios
        for period in periods
        if vintage <= period < vintage + lifetimes[technology]
    ]
    return pd.DataFrame(
        rows, columns=["region", "technology", "vintage", "period", "credit"]
    )


def process_reserve_derates(
    processes: pd.DataFrame,
    ratios: dict[GenerationTechnology, float],
    reproduce_previous_hydro_storage_derate: bool,
) -> pd.DataFrame:
    """
    Reserve capacity derate (dynamic reserve margin) of each process: the IESO ratio
    of its technology, the same in every season.

    Temoa multiplies the derate by the output available in each time slice, so the
    technologies whose hourly capacity factor already is their availability (see
    `GenerationTechnology.has_hourly_capacity_factor`) get none. Nor does the monthly
    hydro reservoir, a storage technology whose discharge Temoa counts: it is
    already limited by the water stored. The previous module derated it
    (`reproduce_previous_hydro_storage_derate`).

    Parameters
    ----------
    processes : pd.DataFrame
        Generators (not the bins), see `generation.parameters.existing_processes`
        and `new_processes`.
    ratios : dict[GenerationTechnology, float]
        See `ieso_capacity_ratios`; technologies without one get no derate.
    reproduce_previous_hydro_storage_derate : bool
        Derate the monthly hydro reservoir too.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `factor`.

    Examples
    --------
    >>> processes = pd.DataFrame(
    ...     {"region": [CANOEProvince.ONTARIO] * 3,
    ...      "technology": [GenerationTechnology.HydroDaily,
    ...                     GenerationTechnology.HydroMonthly,
    ...                     GenerationTechnology.HydroRunOfRiver],
    ...      "vintage": [2024] * 3}
    ... )
    >>> hydro = {t: 0.6 for t in processes["technology"]}
    >>> process_reserve_derates(processes, hydro, False)[["technology", "factor"]]
        technology  factor
    0  hydro_daily     0.6
    >>> len(process_reserve_derates(processes, hydro, True))
    2
    """

    def derated(technology: GenerationTechnology) -> bool:
        if technology not in ratios or technology.has_hourly_capacity_factor():
            return False
        return (
            technology != GenerationTechnology.HydroMonthly
            or reproduce_previous_hydro_storage_derate
        )

    rows = [
        {
            "region": region,
            "technology": technology,
            "vintage": vintage,
            "factor": ratios[technology],
        }
        for region, technology, vintage in zip(
            processes["region"], processes["technology"], processes["vintage"]
        )
        if derated(technology)
    ]
    return pd.DataFrame(rows, columns=["region", "technology", "vintage", "factor"])


def vre_bin_capacity_credits(
    credits: pd.DataFrame,
    technologies: list[GenerationTechnology],
    provinces: list[CANOEProvince],
    periods: list[int],
) -> pd.DataFrame:
    """
    Capacity credit of each new wind and solar bin of `technologies` in `provinces`,
    for the vintages and periods in `periods`.

    Parameters
    ----------
    credits : pd.DataFrame
        See `loaders.get_vre_bin_capacity_credits`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `bin`, `vintage`, `period` and `credit`.

    Raises
    ------
    ValueError
        If a bin has no credit for a vintage.
    """
    selected = credits.loc[
        credits["technology"].isin(technologies)
        & credits["region"].isin(provinces)
        & credits["vintage"].isin(periods)
        & credits["period"].isin(periods)
    ]
    vintages = selected.groupby(["region", "technology", "bin"], sort=False)[
        "vintage"
    ].nunique()
    short = vintages.loc[vintages < len(periods)]
    if not short.empty:
        raise ValueError(
            f"VRE bins without a capacity credit for some vintages: {short.index.tolist()}"
        )
    return selected.reset_index(drop=True)


def planning_reserve_margins(
    margins: pd.DataFrame, provinces: list[CANOEProvince]
) -> pd.DataFrame:
    """
    Planning reserve margin of each of `provinces`.

    Parameters
    ----------
    margins : pd.DataFrame
        See `loaders.get_coders_reserve_margins`.

    Returns
    -------
    pd.DataFrame
        Columns `region` and `margin`, in the order of `provinces`.

    Raises
    ------
    ValueError
        If a province has no margin.
    """
    by_region: dict[CANOEProvince, float] = dict(
        zip(margins["region"], margins["margin"].astype(float))
    )
    missing = [p for p in provinces if p not in by_region]
    if missing:
        raise ValueError(f"No planning reserve margin for {missing}")
    return pd.DataFrame(
        {"region": provinces, "margin": [by_region[p] for p in provinces]}
    )

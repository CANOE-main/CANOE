"""
Reliability parameters: the planning reserve margin of each province and what counts
towards it, plus the ramp rates of the thermal generators.

CANOE writes the dynamic reserve margin only: capacity counts towards the margin
through reserve capacity derates (a share of each process's available output, by
season), not capacity credits (the static reserve margin, a share of each process's
capacity by period), so Temoa must run with `reserve_margin = "dynamic"`. The
derates come from Ontario's capability at the summer peak over its installed
capacity, by fuel (IESO Reliability Outlook), applied to every province (see
`ELECTRICITY_MODULE_BUGS.md`, entry 3).

Storage, the CCS retrofits, the bypasses and the new wind and solar bins get none:
Temoa's default derate of 1 applies.
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

"""
Parameters of the generators: lifetimes, efficiencies, investment and operation and
maintenance costs, the activity of cogeneration, and the new wind and solar bins.

Technologies with an NREL ATB equivalent (`GenerationTechnology.get_atb_display_name`)
take their efficiency and costs from the ATB, the others from CODERS
`generation_generic`; lifetimes always come from CODERS. Each process (region,
technology, vintage) reads the ATB at its `atb_year`: existing vintages at their own
year, new ones at the projection year of their period (see `new_processes`), never
before the first ATB year (2022) or the technology's own first year (2030 for
nuclear).
"""

import numpy as np
import pandas as pd

from canoe.common import CANOEProvince

from ..catalogue import CCSRetrofit, GenerationTechnology, StorageTechnology

type Technology = GenerationTechnology | StorageTechnology | CCSRetrofit
"""Generators, storage and CCS retrofits share the ATB (and CODERS) parameters."""


def generation_lifetimes(generic: pd.DataFrame) -> dict[GenerationTechnology, int]:
    """
    Lifetime (years) of each technology: CODERS `service_life`, or 100 for the
    technologies that never retire (hydro), which outlives any horizon.

    Parameters
    ----------
    generic : pd.DataFrame
        CODERS generic parameters, see `loaders.get_coders_generation_generic`.

    Examples
    --------
    >>> generic = pd.DataFrame(
    ...     {"service_life": [45, 80]},
    ...     index=pd.Index(["ng_sc", "hydro_daily"], name="coders_type"),
    ... )
    >>> lifetimes = generation_lifetimes(generic)
    >>> lifetimes[GenerationTechnology.NaturalGasCT], lifetimes[GenerationTechnology.HydroDaily]
    (45, 100)
    """
    NEVER_RETIRES_LIFETIME = 100
    return {
        technology: NEVER_RETIRES_LIFETIME
        if technology.never_retires()
        else int(generic.loc[technology.get_coders_generic_type(), "service_life"])
        for technology in GenerationTechnology
        if technology.get_coders_generic_type() in generic.index
    }


def existing_processes(fleet: pd.DataFrame) -> pd.DataFrame:
    """
    The (region, technology, vintage) of the existing fleet, reading the ATB at
    the vintage year.

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `atb_year`.
    """
    return pd.DataFrame(
        {
            "region": fleet["region"],
            "technology": fleet["technology"],
            "vintage": fleet["vintage"],
            "atb_year": fleet["vintage"],
        }
    ).reset_index(drop=True)


def new_processes(
    technologies: list[Technology],
    provinces: list[CANOEProvince],
    projection_years: dict[int, int],
) -> pd.DataFrame:
    """
    New capacity of `technologies` in every province, one vintage per period,
    reading the ATB at the projection year of the period.

    Parameters
    ----------
    technologies : list[Technology]
        New technologies: generators (not binned, see
        `GenerationTechnology.is_resource_binned`) or storage.
    provinces : list[CANOEProvince]
        Regions modelled.
    projection_years : dict[int, int]
        Period -> year, see `common.periods.projection_year_by_period`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `atb_year`.

    Examples
    --------
    >>> new_processes(
    ...     [GenerationTechnology.NaturalGasCC], [CANOEProvince.ONTARIO],
    ...     {2025: 2030, 2030: 2035},
    ... )[["technology", "vintage", "atb_year"]]
      technology  vintage  atb_year
    0      ng_cc     2025      2030
    1      ng_cc     2030      2035
    """
    return pd.DataFrame(
        [
            {
                "region": region,
                "technology": technology,
                "vintage": vintage,
                "atb_year": year,
            }
            for technology in technologies
            for region in provinces
            for vintage, year in projection_years.items()
        ],
        columns=["region", "technology", "vintage", "atb_year"],
    )


def process_efficiencies(
    processes: pd.DataFrame, generic: pd.DataFrame, atb: pd.DataFrame
) -> pd.DataFrame:
    """
    Efficiency (PJ of electricity per PJ of input) of each process:

    - 1 for free resources (`E_ethos`: water, wind, sun, heat), whose input is
      counted as the electricity it produces;
    - ATB technologies: 1 / heat rate at the process's `atb_year`;
    - otherwise CODERS `efficiency`.

    Parameters
    ----------
    processes : pd.DataFrame
        See `existing_processes` and `new_processes`.
    generic : pd.DataFrame
        See `loaders.get_coders_generation_generic`.
    atb : pd.DataFrame
        See `loaders.get_atb_generation`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `efficiency`.

    Raises
    ------
    ValueError
        If a fuel-burning technology has no efficiency.

    Examples
    --------
    A gas turbine with an ATB heat rate of 9.72 MMBtu/MWh in 2022 (3.412 MMBtu per
    MWh is 100%), and a dam:

    >>> ON = CANOEProvince.ONTARIO
    >>> processes = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON],
    ...         "technology": [GenerationTechnology.NaturalGasCT, GenerationTechnology.HydroDaily],
    ...         "vintage": [2010, 2024],
    ...         "atb_year": [2010, 2024],
    ...     }
    ... )
    >>> atb = pd.DataFrame(
    ...     {
    ...         "display_name": ["NG Combustion Turbine (F-Frame)"],
    ...         "parameter": ["Heat Rate"],
    ...         "year": [2022],
    ...         "value": [9.72],
    ...     }
    ... )
    >>> process_efficiencies(processes, pd.DataFrame(), atb)["efficiency"].round(4).tolist()
    [0.351, 1.0]
    """
    MWH_PER_MMBTU = 0.29307107

    def efficiency(technology: GenerationTechnology, year: int) -> float:
        if technology.get_input_fuel() is None:
            return 1.0
        if technology.get_atb_display_name() is not None:
            heat_rate = atb_value(atb, technology, "Heat Rate", year)
            return 1 / (heat_rate * MWH_PER_MMBTU)
        return float(generic.loc[technology.get_coders_generic_type(), "efficiency"])

    efficiencies = pd.DataFrame(
        {
            "region": processes["region"],
            "technology": processes["technology"],
            "vintage": processes["vintage"],
            "efficiency": [
                efficiency(t, y)
                for t, y in zip(processes["technology"], processes["atb_year"])
            ],
        }
    )
    missing = efficiencies.loc[~(efficiencies["efficiency"] > 0)]
    if not missing.empty:
        raise ValueError(f"Generators without an efficiency:\n{missing}")
    return efficiencies


def process_investment_costs(
    processes: pd.DataFrame,
    atb: pd.DataFrame,
    atb_conversion: float,
    metric: str = "OCC",
) -> pd.DataFrame:
    """
    Investment cost of each new process: the ATB overnight capital cost (`metric`;
    `Additional OCC` for CCS retrofits) at the process's `atb_year`, in M$/GW of the
    model currency ($/kW is M$/GW).

    Parameters
    ----------
    processes : pd.DataFrame
        See `new_processes`; ATB technologies only.
    atb : pd.DataFrame
        See `loaders.get_atb_generation`.
    atb_conversion : float
        Factor from the ATB currency to the model currency.
    metric : str
        ATB investment parameter, `OCC` by default.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `cost`.

    Raises
    ------
    ValueError
        If a process has no ATB investment cost.

    Examples
    --------
    >>> processes = new_processes(
    ...     [GenerationTechnology.NuclearSMR], [CANOEProvince.ONTARIO], {2025: 2025}
    ... )
    >>> atb = pd.DataFrame(
    ...     {
    ...         "display_name": ["Nuclear - Small"] * 2,
    ...         "parameter": ["OCC"] * 2,
    ...         "year": [2025, 2030],
    ...         "value": [12000.0, 10000.0],
    ...     }
    ... )
    >>> process_investment_costs(processes, atb, 1.0)["cost"].tolist()  # from 2030
    [10000.0]
    """
    costs = pd.DataFrame(
        {
            "region": processes["region"],
            "technology": processes["technology"],
            "vintage": processes["vintage"],
            "cost": [
                atb_value(atb, t, metric, y) * atb_conversion
                for t, y in zip(processes["technology"], processes["atb_year"])
            ],
        }
    )
    missing = costs.loc[~(costs["cost"] > 0)]
    if not missing.empty:
        raise ValueError(f"New generators without an investment cost:\n{missing}")
    return costs


def process_om_costs[T: (GenerationTechnology, StorageTechnology)](
    processes: pd.DataFrame,
    generic: pd.DataFrame,
    atb: pd.DataFrame,
    lifetimes: dict[T, int],
    periods: list[int],
    atb_conversion: float,
    coders_conversion: float,
) -> pd.DataFrame:
    """
    Fixed and variable operation and maintenance costs of each process, in the
    periods its vintage lives, in M$ of the model currency. Fuel is not included:
    the fuel module prices it.

    The costs of a vintage are the same in every period: ATB technologies take the
    ATB values at the process's `atb_year`, the others CODERS `fixed_om_costs` and
    `variable_om_costs`. Zero costs are left out (NaN).

    Parameters
    ----------
    processes : pd.DataFrame
        See `existing_processes` and `new_processes`.
    generic, atb : pd.DataFrame
        See `loaders.get_coders_generation_generic` and `loaders.get_atb_generation`.
    lifetimes : dict[Technology, int]
        See `generation_lifetimes` and `storage_lifetimes`.
    periods : list[int]
        Model periods.
    atb_conversion, coders_conversion : float
        Factors from the ATB and CODERS currencies to the model currency, see
        `common.currency.currency_conversion_factor`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage`, `period`, `fixed` (M$/GW-year)
        and `variable` (M$/PJ).

    Examples
    --------
    A 2010 diesel turbine with a 30-year life lives in 2025-2035; CODERS gives
    47,853 $/MW-year and 8.32 $/MWh:

    >>> processes = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ONTARIO],
    ...         "technology": [GenerationTechnology.DieselCT],
    ...         "vintage": [2010],
    ...         "atb_year": [2010],
    ...     }
    ... )
    >>> generic = pd.DataFrame(
    ...     {"fixed_om": [47853.0], "variable_om": [8.32]},
    ...     index=pd.Index(["diesel_ct"], name="coders_type"),
    ... )
    >>> costs = process_om_costs(
    ...     processes, generic, pd.DataFrame(), {GenerationTechnology.DieselCT: 30},
    ...     [2025, 2030, 2035, 2040], atb_conversion=1.0, coders_conversion=1.0,
    ... )
    >>> costs[["period", "fixed", "variable"]].round(3)
       period   fixed  variable
    0    2025  47.853     2.311
    1    2030  47.853     2.311
    2    2035  47.853     2.311
    """
    PER_MW_TO_PER_GW = 1e-3  # $/MW -> M$/GW
    PER_MWH_TO_PER_PJ = 1 / 3.6  # $/MWh -> M$/PJ

    def costs(technology: T, year: int) -> tuple[float, float]:
        if technology.get_atb_display_name() is not None:
            # $/kW-year is M$/GW-year
            fixed = atb_value(atb, technology, "Fixed O&M", year)
            variable = atb_value(atb, technology, "Variable O&M", year)
            return fixed * atb_conversion, variable * PER_MWH_TO_PER_PJ * atb_conversion
        row = generic.loc[technology.get_coders_generic_type()]
        return (
            float(row["fixed_om"]) * PER_MW_TO_PER_GW * coders_conversion,
            float(row["variable_om"]) * PER_MWH_TO_PER_PJ * coders_conversion,
        )

    rows: list[dict[str, object]] = []
    for region, technology, vintage, year in zip(
        processes["region"],
        processes["technology"],
        processes["vintage"],
        processes["atb_year"],
    ):
        fixed, variable = costs(technology, year)
        for period in periods:
            if vintage <= period < vintage + lifetimes[technology]:
                rows.append(
                    {
                        "region": region,
                        "technology": technology,
                        "vintage": vintage,
                        "period": period,
                        "fixed": fixed or np.nan,
                        "variable": variable or np.nan,
                    }
                )
    return pd.DataFrame(
        rows, columns=["region", "technology", "vintage", "period", "fixed", "variable"]
    )


def cogeneration_activity(
    fleet: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    periods: list[int],
    floor_share: float,
) -> pd.DataFrame:
    """
    Bounds on the annual output of the existing cogeneration, in each region and
    period where some of it lives: at most the CODERS average annual output of the
    surviving vintages, at least `floor_share` of it.

    The model does not represent the heat of cogeneration, so it would otherwise
    dispatch these plants as plain generators; the host sites need their heat, so
    their electricity output is held at its historical level.

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation_lifetimes`.
    periods : list[int]
        Model periods.
    floor_share : float
        Lower bound as a share of the upper bound (slack for the solver).

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `period`, `min_activity` and
        `max_activity` (PJ).

    Examples
    --------
    Two vintages of gas cogeneration; the 2000 one (30-year life) retires in 2030:

    >>> fleet = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ALBERTA] * 2,
    ...         "technology": [GenerationTechnology.NaturalGasCogeneration] * 2,
    ...         "vintage": [2000, 2020],
    ...         "annual_energy": [60.0, 40.0],
    ...     }
    ... )
    >>> cogeneration_activity(
    ...     fleet, {GenerationTechnology.NaturalGasCogeneration: 30}, [2025, 2030], 0.95
    ... )[["period", "min_activity", "max_activity"]]
       period  min_activity  max_activity
    0    2025          95.0         100.0
    1    2030          38.0          40.0
    """
    technologies: list[GenerationTechnology] = list(fleet["technology"])
    cogeneration = fleet.loc[[t.is_cogeneration() for t in technologies]]
    rows: list[dict[str, object]] = []
    for (region, technology), group in cogeneration.groupby(
        ["region", "technology"], sort=False
    ):
        for period in periods:
            alive = group["vintage"] + lifetimes[technology] > period
            if not alive.any():
                continue
            energy = float(group.loc[alive, "annual_energy"].sum())
            rows.append(
                {
                    "region": region,
                    "technology": technology,
                    "period": period,
                    "min_activity": floor_share * energy,
                    "max_activity": energy,
                }
            )
    return pd.DataFrame(
        rows,
        columns=["region", "technology", "period", "min_activity", "max_activity"],
    )


def vre_bin_costs(
    investment: pd.DataFrame,
    fixed: pd.DataFrame,
    technologies: list[GenerationTechnology],
    provinces: list[CANOEProvince],
    periods: list[int],
    lifetimes: dict[GenerationTechnology, int],
    conversion: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Investment and fixed costs of the new wind and solar bins of `technologies` in
    `provinces`, one vintage per period, in M$ of the model currency ($/kW is M$/GW).
    The fixed cost of a vintage is the same in every period it lives.

    Parameters
    ----------
    investment, fixed : pd.DataFrame
        Costs of the bins, see `loaders.get_vre_bin_investment_costs` and
        `loaders.get_vre_bin_fixed_costs`.
    technologies : list[GenerationTechnology]
        The binned technologies modelled.
    provinces : list[CANOEProvince]
        Regions modelled.
    periods : list[int]
        Model periods, the vintages.
    lifetimes : dict[GenerationTechnology, int]
        See `generation_lifetimes`.
    conversion : float
        Factor from the bins' currency to the model currency.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Investment costs (columns `region`, `technology`, `bin`, `vintage`, `cost`,
        M$/GW) and fixed costs (plus `period`, M$/GW-year).

    Raises
    ------
    ValueError
        If a bin lacks the costs of a vintage.

    Examples
    --------
    >>> ON, WIND = CANOEProvince.ONTARIO, GenerationTechnology.WindOnshore
    >>> costs = pd.DataFrame(
    ...     {"region": [ON, ON], "technology": [WIND, WIND], "bin": [1, 1],
    ...      "vintage": [2025, 2030], "cost": [1000.0, 900.0]}
    ... )
    >>> invest, fixed = vre_bin_costs(
    ...     costs, costs.assign(cost=[30.0, 29.0]), [WIND], [ON], [2025, 2030],
    ...     {WIND: 30}, 1.0,
    ... )
    >>> fixed[["vintage", "period", "cost"]]
       vintage  period  cost
    0     2025    2025  30.0
    1     2025    2030  30.0
    2     2030    2030  29.0
    """
    keys = ["region", "technology", "bin", "vintage"]

    def select(costs: pd.DataFrame, name: str) -> pd.DataFrame:
        selected = costs.loc[
            costs["technology"].isin(technologies) & costs["region"].isin(provinces)
        ]
        bins = selected[["region", "technology", "bin"]].drop_duplicates()
        expected = bins.merge(pd.DataFrame({"vintage": periods}), how="cross")
        found = expected.merge(selected, on=keys, how="left")
        missing = found.loc[found["cost"].isna(), keys]
        if not missing.empty:
            raise ValueError(f"VRE bins without {name} cost for\n{missing}")
        found["cost"] *= conversion
        return found[[*keys, "cost"]]

    invest = select(investment, "an investment")
    by_vintage = select(fixed, "a fixed")
    fixed_rows = [
        {**row, "period": period}
        for row in by_vintage.to_dict("records")
        for period in periods
        if row["vintage"] <= period < row["vintage"] + lifetimes[row["technology"]]
    ]
    return invest, pd.DataFrame(
        fixed_rows, columns=[*keys[:3], "vintage", "period", "cost"]
    )


def vre_bin_limits(
    limits: pd.DataFrame,
    technologies: list[GenerationTechnology],
    provinces: list[CANOEProvince],
    periods: list[int],
) -> pd.DataFrame:
    """
    Largest capacity (GW) of each new wind and solar bin of `technologies` in
    `provinces`, in each period.

    Parameters
    ----------
    limits : pd.DataFrame
        See `loaders.get_vre_bin_capacity_limits`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `bin`, `period` and `capacity`.

    Raises
    ------
    ValueError
        If a bin has no limit in a period.
    """
    selected = limits.loc[
        limits["technology"].isin(technologies)
        & limits["region"].isin(provinces)
        & limits["period"].isin(periods)
    ]
    counts = selected.groupby(["region", "technology", "bin"], sort=False).size()
    short = counts.loc[counts < len(periods)]
    if not short.empty:
        raise ValueError(
            f"VRE bins without a capacity limit in some periods: {short.index.tolist()}"
        )
    return selected.reset_index(drop=True)


def vre_bin_capacity_factors(
    factors: pd.DataFrame,
    technologies: list[GenerationTechnology],
    provinces: list[CANOEProvince],
    periods: list[int],
    tolerance: float,
) -> pd.DataFrame:
    """
    Hourly capacity factor of each new wind and solar bin of `technologies` in
    `provinces`, for the vintages in `periods`; those below `tolerance` set to 0.

    Parameters
    ----------
    factors : pd.DataFrame
        See `loaders.get_vre_bin_capacity_factors`.
    tolerance : float
        Smallest capacity factor kept (noise in the data).

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `bin`, `vintage`, `hour` and `factor`.

    Raises
    ------
    ValueError
        If a bin lacks the hours of a vintage.
    """
    HOURS = 8760
    selected = factors.loc[
        factors["technology"].isin(technologies)
        & factors["region"].isin(provinces)
        & factors["vintage"].isin(periods)
    ]
    counts = selected.groupby(["region", "technology", "bin"], sort=False).size()
    short = counts.loc[counts != HOURS * len(periods)]
    if not short.empty:
        raise ValueError(
            "VRE bins without the hourly capacity factors of every vintage: "
            + f"{short.index.tolist()}"
        )
    return selected.assign(
        factor=selected["factor"].mask(selected["factor"] < tolerance, 0.0)
    ).reset_index(drop=True)


def atb_value(
    atb: pd.DataFrame, technology: Technology, parameter: str, year: int
) -> float:
    """ATB value of `technology` at `year`, not before the first year the ATB has
    nor the technology's first year (NaN if the ATB has no value for the
    parameter)"""
    values = atb.loc[
        (atb["display_name"] == technology.get_atb_display_name())
        & (atb["parameter"] == parameter)
    ]
    if values.empty:
        return np.nan
    first_year = max(int(values["year"].min()), technology.get_atb_first_year() or 0)
    at_year = values.loc[values["year"] == max(year, first_year)]
    return float(at_year["value"].iloc[0]) if not at_year.empty else np.nan

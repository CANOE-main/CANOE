"""
Parameters of the existing generators: lifetimes, efficiencies, operation and
maintenance costs, and the activity of cogeneration.

Technologies with an NREL ATB equivalent (`GenerationTechnology.get_atb_display_name`)
take their efficiency and costs from the ATB, the others from CODERS
`generation_generic`; lifetimes always come from CODERS. ATB values are read at the
vintage year, or the first ATB year (2022) for older vintages.
"""

import numpy as np
import pandas as pd

from ..catalogue import GenerationTechnology


def existing_lifetimes(generic: pd.DataFrame) -> dict[GenerationTechnology, int]:
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
    >>> lifetimes = existing_lifetimes(generic)
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


def existing_efficiencies(
    fleet: pd.DataFrame, generic: pd.DataFrame, atb: pd.DataFrame
) -> pd.DataFrame:
    """
    Efficiency (PJ of electricity per PJ of input) of each (region, technology,
    vintage) of the fleet:

    - 1 for free resources (`E_ethos`: water, wind, sun, heat), whose input is
      counted as the electricity it produces;
    - ATB technologies: 1 / heat rate at the vintage year;
    - otherwise CODERS `efficiency`.

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
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

    >>> from canoe.common import CANOEProvince
    >>> ON = CANOEProvince.ONTARIO
    >>> fleet = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON],
    ...         "technology": [GenerationTechnology.NaturalGasCT, GenerationTechnology.HydroDaily],
    ...         "vintage": [2010, 2024],
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
    >>> existing_efficiencies(fleet, pd.DataFrame(), atb)["efficiency"].round(4).tolist()
    [0.351, 1.0]
    """
    MWH_PER_MMBTU = 0.29307107

    def efficiency(technology: GenerationTechnology, vintage: int) -> float:
        if technology.get_input_fuel() is None:
            return 1.0
        display_name = technology.get_atb_display_name()
        if display_name is not None:
            heat_rate = _atb_value(atb, display_name, "Heat Rate", vintage)
            return 1 / (heat_rate * MWH_PER_MMBTU)
        return float(generic.loc[technology.get_coders_generic_type(), "efficiency"])

    efficiencies = pd.DataFrame(
        {
            "region": fleet["region"],
            "technology": fleet["technology"],
            "vintage": fleet["vintage"],
            "efficiency": [
                efficiency(t, v) for t, v in zip(fleet["technology"], fleet["vintage"])
            ],
        }
    )
    missing = efficiencies.loc[~(efficiencies["efficiency"] > 0)]
    if not missing.empty:
        raise ValueError(f"Existing generators without an efficiency:\n{missing}")
    return efficiencies


def existing_om_costs(
    fleet: pd.DataFrame,
    generic: pd.DataFrame,
    atb: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    periods: list[int],
    atb_conversion: float,
    coders_conversion: float,
) -> pd.DataFrame:
    """
    Fixed and variable operation and maintenance costs of each (region,
    technology, vintage) of the fleet, in the periods the vintage lives, in M$ of
    the model currency. Fuel is not included: the fuel module prices it.

    The costs of a vintage are the same in every period: ATB technologies take the
    ATB values at the vintage year, the others CODERS `fixed_om_costs` and
    `variable_om_costs`. Zero costs are left out (NaN).

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
    generic, atb : pd.DataFrame
        See `loaders.get_coders_generation_generic` and `loaders.get_atb_generation`.
    lifetimes : dict[GenerationTechnology, int]
        See `existing_lifetimes`.
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

    >>> from canoe.common import CANOEProvince
    >>> fleet = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ONTARIO],
    ...         "technology": [GenerationTechnology.DieselCT],
    ...         "vintage": [2010],
    ...     }
    ... )
    >>> generic = pd.DataFrame(
    ...     {"fixed_om": [47853.0], "variable_om": [8.32]},
    ...     index=pd.Index(["diesel_ct"], name="coders_type"),
    ... )
    >>> costs = existing_om_costs(
    ...     fleet, generic, pd.DataFrame(), {GenerationTechnology.DieselCT: 30},
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

    def costs(technology: GenerationTechnology, vintage: int) -> tuple[float, float]:
        display_name = technology.get_atb_display_name()
        if display_name is not None:
            # $/kW-year is M$/GW-year
            fixed = _atb_value(atb, display_name, "Fixed O&M", vintage)
            variable = _atb_value(atb, display_name, "Variable O&M", vintage)
            return fixed * atb_conversion, variable * PER_MWH_TO_PER_PJ * atb_conversion
        row = generic.loc[technology.get_coders_generic_type()]
        return (
            float(row["fixed_om"]) * PER_MW_TO_PER_GW * coders_conversion,
            float(row["variable_om"]) * PER_MWH_TO_PER_PJ * coders_conversion,
        )

    rows: list[dict[str, object]] = []
    for region, technology, vintage in zip(
        fleet["region"], fleet["technology"], fleet["vintage"]
    ):
        fixed, variable = costs(technology, vintage)
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
        See `existing_lifetimes`.
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

    >>> from canoe.common import CANOEProvince
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


def _atb_value(
    atb: pd.DataFrame, display_name: str, parameter: str, year: int
) -> float:
    """ATB value at `year`, or at the first year the ATB has if earlier (NaN if the
    ATB has no value for the parameter)"""
    values = atb.loc[
        (atb["display_name"] == display_name) & (atb["parameter"] == parameter)
    ]
    if values.empty:
        return np.nan
    at_year = values.loc[values["year"] == max(year, int(values["year"].min()))]
    return float(at_year["value"].iloc[0]) if not at_year.empty else np.nan

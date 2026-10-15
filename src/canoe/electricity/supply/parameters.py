"""
Parameters of the grid: line losses, and transmission and distribution costs.
"""

import pandas as pd

from canoe.common import CANOEProvince

from ..catalogue import GridLevel
from ..loaders import SourceCosts


def transmission_efficiencies(
    line_losses: pd.DataFrame, provinces: list[CANOEProvince]
) -> pd.DataFrame:
    """
    Efficiency of the transmission to distribution step of each province: one minus
    the system line losses, so all grid losses (transmission and distribution) are
    taken there.

    Parameters
    ----------
    line_losses : pd.DataFrame
        Columns `region` and `line_losses` (fraction), see
        `loaders.get_coders_system_line_losses`.
    provinces : list[CANOEProvince]
        Provinces modelled; every one needs its losses.

    Returns
    -------
    pd.DataFrame
        Columns `region` and `efficiency`, in the order of `provinces`.

    Raises
    ------
    ValueError
        If a province has no losses.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> losses = pd.DataFrame({"region": [QC, ON], "line_losses": [0.074, 0.08]})
    >>> transmission_efficiencies(losses, [ON, QC])["efficiency"].round(3).tolist()
    [0.92, 0.926]
    """
    by_region: dict[CANOEProvince, float] = dict(
        zip(line_losses["region"], line_losses["line_losses"])
    )
    missing = [p.short() for p in provinces if p not in by_region]
    if missing:
        raise ValueError(f"No system line losses for {missing}")
    return pd.DataFrame(
        {
            "region": provinces,
            "efficiency": [1.0 - by_region[p] for p in provinces],
        }
    )


def grid_variable_costs(
    source: SourceCosts, projection_years: dict[int, int], currency_factor: float
) -> pd.DataFrame:
    """
    Variable cost of each grid level in each model period, in M$/PJ of the model
    currency: the source's cost per kWh delivered, read at the projection year of
    each period.

    Parameters
    ----------
    source : SourceCosts
        Costs in c/kWh, columns `level`, `year` and `cost`, see
        `loaders.get_aeo_transmission_distribution_costs`.
    projection_years : dict[int, int]
        Model period -> year read, see `canoe.common.periods.projection_year_by_period`.
    currency_factor : float
        Converts the source's currency to the model's, see
        `canoe.common.currency.currency_conversion_factor`.

    Returns
    -------
    pd.DataFrame
        Columns `level` (`GridLevel`), `period` and `cost`.

    Raises
    ------
    ValueError
        If a projection year is not in the source.

    Examples
    --------
    >>> source = SourceCosts(
    ...     costs=pd.DataFrame(
    ...         {
    ...             "level": [GridLevel.Transmission, GridLevel.Distribution] * 2,
    ...             "year": [2030, 2030, 2035, 2035],
    ...             "cost": [2.0, 3.6, 2.2, 3.7],
    ...         }
    ...     ),
    ...     currency="USD",
    ...     currency_year=2024,
    ...     units="c/kWh",
    ...     reference="",
    ... )
    >>> costs = grid_variable_costs(source, {2025: 2030, 2030: 2035}, currency_factor=1.0)
    >>> print(costs.assign(cost=costs["cost"].round(4)).to_string(index=False))
    level  period    cost
       tx    2025  5.5556
       tx    2030  6.1111
       dx    2025 10.0000
       dx    2030 10.2778
    """
    if source.units != "c/kWh":
        raise ValueError(f"Grid costs in {source.units}, expected c/kWh")
    # c/kWh -> M$/PJ: 1 PJ = 1e15 / 3.6e6 kWh, 100 c per $, 1e6 $ per M$
    units_factor = 1e15 / 3.6e6 / 100 / 1e6
    costs: dict[tuple[GridLevel, int], float] = {
        (GridLevel(level), int(year)): float(cost)
        for level, year, cost in zip(
            source.costs["level"], source.costs["year"], source.costs["cost"]
        )
    }
    rows: list[dict[str, object]] = []
    for level in GridLevel:
        for period, year in projection_years.items():
            if (level, year) not in costs:
                raise ValueError(f"No {level.name.lower()} cost for {year}")
            rows.append(
                {
                    "level": level,
                    "period": period,
                    "cost": float(costs[(level, year)])
                    * units_factor
                    * currency_factor,
                }
            )
    return pd.DataFrame(rows)


def exogenous_demands(
    annual: pd.DataFrame,
    provinces: list[CANOEProvince],
    projection_years: dict[int, int],
) -> pd.DataFrame:
    """
    Electricity demand of each province in each period (PJ): the forecast at the
    projection year of the period.

    Parameters
    ----------
    annual : pd.DataFrame
        Columns `region`, `year` and `demand` (GWh), see
        `loaders.get_coders_annual_demand`.
    provinces : list[CANOEProvince]
        Provinces modelled.
    projection_years : dict[int, int]
        Model period -> year read, see `canoe.common.periods.projection_year_by_period`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `period` and `demand`.

    Raises
    ------
    ValueError
        If a province has no forecast for a projection year.

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> annual = pd.DataFrame({"region": [ON, ON], "year": [2030, 2035], "demand": [1e5, 2e5]})
    >>> exogenous_demands(annual, [ON], {2025: 2030, 2030: 2035})["demand"].tolist()
    [360.0, 720.0]
    """
    GWH_TO_PJ = 0.0036
    by_key: dict[tuple[CANOEProvince, int], float] = {
        (r, int(y)): float(d)
        for r, y, d in zip(annual["region"], annual["year"], annual["demand"])
    }
    rows: list[dict[str, object]] = []
    for region in provinces:
        for period, year in projection_years.items():
            if (region, year) not in by_key:
                raise ValueError(
                    f"No CODERS demand forecast for {region.short()} {year}"
                )
            rows.append(
                {
                    "region": region,
                    "period": period,
                    "demand": by_key[(region, year)] * GWH_TO_PJ,
                }
            )
    return pd.DataFrame(rows, columns=["region", "period", "demand"])


def exogenous_demand_profiles(
    hourly: pd.DataFrame, provinces: list[CANOEProvince], tolerance: float
) -> pd.DataFrame:
    """
    Share of each province's yearly demand in each hour; hours below `tolerance` times
    the average hour are set to 0 (gaps and noise in the data).

    Parameters
    ----------
    hourly : pd.DataFrame
        Columns `region`, `hour` and `demand` (MWh), see
        `loaders.get_coders_provincial_demand`.
    provinces : list[CANOEProvince]
        Provinces modelled; every one needs its hours.
    tolerance : float
        Share of the average hour below which an hour is set to 0.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `hour` and `share`.

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> hourly = pd.DataFrame({"region": ON, "hour": [0, 1, 2], "demand": [1.0, 3.0, 0.01]})
    >>> exogenous_demand_profiles(hourly, [ON], 0.02)["share"].tolist()
    [0.25, 0.75, 0.0]
    """
    missing = sorted(p.short() for p in provinces if p not in set(hourly["region"]))
    if missing:
        raise ValueError(f"No hourly demand for {missing}")
    selected = hourly.loc[hourly["region"].isin(provinces)]
    average = selected.groupby("region")["demand"].transform("mean")
    demand = selected["demand"].mask(selected["demand"] < average * tolerance, 0.0)
    total = demand.groupby(selected["region"]).transform("sum")
    return pd.DataFrame(
        {
            "region": selected["region"],
            "hour": selected["hour"],
            "share": demand / total,
        }
    ).reset_index(drop=True)

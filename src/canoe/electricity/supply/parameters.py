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

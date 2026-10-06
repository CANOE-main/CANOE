"""
The existing stock of the residential end uses: the pieces every end use group
shares to turn its base-year stock, efficiencies and capacity factors into the
parameters of its existing technologies (`entities.ExistingTechnologyParameters`).
Nothing in here touches the database.

The NRCan stock of the CEUD data year stands at the start of the first model period
(see `RESIDENTIAL_MODULE_BUGS.md`), spread over the existing vintages alive then
(`canoe.common.periods.existing_stock_vintages`).
"""

from dataclasses import dataclass

import pandas as pd
from canoe_schema.v4_0 import OperatorCode
from loguru import logger
from scipy.special import gamma

from canoe.common import CANOEProvince
from canoe.common.periods import existing_stock_vintages

from .entities import ExistingTechnologyParameters
from .technology_catalog import ExistingTechnology


@dataclass(frozen=True)
class EndUseStock:
    """
    The existing technologies of a group of end uses and the base-year demand they
    serve.

    Parameters
    ----------
    technologies : list[ExistingTechnology]
        Technologies of the group (those without capacity are left out when built).
    parameters : ExistingTechnologyParameters
        Their parameters.
    base_demand : pd.DataFrame
        Columns `region`, `end_use`, `demand`: demand in the CEUD data year (the
        output of the existing stock), in the end use's demand units.
    demand_notes : str
        Notes of the demand rows.
    capacity_factor : pd.DataFrame
        Columns `region`, `technology`, `factor`: annual capacity factor of each
        technology where the previous module wrote one (where it has stock, whatever
        the capacity tolerance; appliances: every region). New technologies take the
        factor of their equivalent existing technology from here.
    """

    technologies: list[ExistingTechnology]
    parameters: ExistingTechnologyParameters
    base_demand: pd.DataFrame
    demand_notes: str
    capacity_factor: pd.DataFrame


def aeo_class_lifetimes(classes: pd.DataFrame) -> dict[str, float]:
    """
    Lifetime (years) of each AEO equipment class: the mean of its Weibull
    distribution, `lambda * gamma(1 + 1/k)`, rounded. Heat pump classes have a row
    per end use: the first one is taken.

    params:
    - classes: see `loaders.AEOTechnologyMenu.classes`

    Examples
    --------
    >>> classes = pd.DataFrame(
    ...     {"equipment_class": ["ELEC_HP", "ELEC_HP"], "weibull_lambda": [15.0, 99.0], "weibull_k": [2.0, 1.0]}
    ... )
    >>> aeo_class_lifetimes(classes)
    {'ELEC_HP': 13.0}
    """
    first = classes.drop_duplicates("equipment_class")
    return {
        str(name): float(round(lam * gamma(1 + 1 / k)))
        for name, lam, k in zip(
            first["equipment_class"], first["weibull_lambda"], first["weibull_k"]
        )
    }


def equivalent_lifetimes(
    technologies: list[ExistingTechnology], class_lifetimes: dict[str, float]
) -> dict[ExistingTechnology, float]:
    """
    Lifetime of each existing technology: that of the AEO class of its equivalent
    new technology (`ExistingTechnologySpec.new_equivalent`).
    """
    lifetimes: dict[ExistingTechnology, float] = {}
    for technology in technologies:
        equivalent = technology.spec().new_equivalent
        aeo_class = equivalent.spec().aeo_class if equivalent is not None else None
        if aeo_class is None:
            raise ValueError(
                f"{technology.value} has no AEO class to take a lifetime from"
            )
        lifetimes[technology] = class_lifetimes[aeo_class]
    return lifetimes


def equivalent_fixed_costs(
    technologies: list[ExistingTechnology], currency_factor: float
) -> pd.DataFrame:
    """
    Fixed cost of each existing technology: that of its equivalent new technology
    (EIA, USD per unit and year), in M$ of the model currency per unit of capacity
    and year.

    params:
    - currency_factor: USD of the AEO cost year to CAD of the model currency year

    Returns technology, cost
    """
    rows: list[tuple[ExistingTechnology, float]] = []
    for technology in technologies:
        spec = technology.spec()
        equivalent = spec.new_equivalent
        fixed_cost = equivalent.spec().fixed_cost if equivalent is not None else None
        if fixed_cost is None:
            raise ValueError(f"{technology.value} has no fixed cost to take")
        rows.append(
            (technology, fixed_cost * spec.end_use.cost_factor() * currency_factor)
        )
    return pd.DataFrame(rows, columns=["technology", "cost"])


def existing_vintages(
    lifetimes: dict[ExistingTechnology, float], first_period: int, period_step: int
) -> pd.DataFrame:
    """
    The existing vintages of each technology and the share of its stock in each, see
    `canoe.common.periods.existing_stock_vintages`.

    Returns technology, vintage, share
    """
    return pd.DataFrame(
        [
            (technology, vintage, share)
            for technology, lifetime in lifetimes.items()
            for vintage, share in existing_stock_vintages(
                lifetime, first_period, period_step
            ).items()
        ],
        columns=["technology", "vintage", "share"],
    )


def capacity_factor_band(factors: pd.DataFrame) -> pd.DataFrame:
    """
    A band around each annual capacity factor: at most the factor (`le`) and at least
    95% of it (`ge`), so the stock is used in consistent proportions with some slack.

    params:
    - factors: any columns and `factor`

    Returns the same columns and `operator`, two rows per row of `factors`

    Examples
    --------
    >>> capacity_factor_band(pd.DataFrame({"vintage": [2020], "factor": [0.2]}))
       vintage  factor operator
    0     2020    0.19       ge
    1     2020    0.20       le
    """
    lower = factors.assign(factor=factors["factor"] * 0.95, operator=OperatorCode.GE)
    upper = factors.assign(operator=OperatorCode.LE)
    return pd.concat([lower, upper], ignore_index=True).sort_values(
        [*factors.columns.drop("factor"), "operator"], ignore_index=True
    )


def costs_while_alive(
    costs: pd.DataFrame, lifetime: pd.DataFrame, model_periods: list[int]
) -> pd.DataFrame:
    """
    Each (vintage) cost in every model period the vintage is alive in: from the
    vintage's period (the first model period for existing vintages) up to, not
    including, `vintage + lifetime`.

    params:
    - costs: any columns, among them `technology` and `vintage`, and `cost`
    - lifetime: columns `technology`, `lifetime`, and `vintage` for lifetimes by
      vintage

    Returns the columns of `costs` and `period`

    Examples
    --------
    >>> costs = pd.DataFrame({"technology": ["T"], "vintage": [2020], "cost": [1.0]})
    >>> lifetime = pd.DataFrame({"technology": ["T"], "lifetime": [12.0]})
    >>> costs_while_alive(costs, lifetime, [2025, 2030, 2035])
      technology  vintage  cost  period
    0          T     2020   1.0    2025
    1          T     2020   1.0    2030
    """
    keys = ["technology", "vintage"] if "vintage" in lifetime else ["technology"]
    by_period = costs.merge(lifetime, on=keys).merge(
        pd.DataFrame({"period": model_periods}), how="cross"
    )
    alive = (by_period["period"] >= by_period["vintage"]) & (
        by_period["vintage"] + by_period["lifetime"] > by_period["period"]
    )
    return by_period.loc[alive, [*costs.columns, "period"]].reset_index(drop=True)


def existing_technology_parameters(
    stock: pd.DataFrame,
    efficiency: pd.DataFrame,
    capacity_factor: pd.DataFrame,
    vintages: pd.DataFrame,
    lifetime: pd.DataFrame,
    fixed_cost: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    capacity_tolerance: float,
    efficiency_notes: str,
    existing_capacity_notes: str,
    capacity_factor_notes: str,
    lifetime_notes: str,
    fixed_cost_notes: str,
) -> ExistingTechnologyParameters:
    """
    Parameters of existing technologies from their base-year stock.

    The stock of each (region, technology) is spread over its vintages; a
    (region, technology) whose existing capacity adds up to less than
    `capacity_tolerance` is left out (logged), as in the previous module. The
    capacity factor is written as a band (`capacity_factor_band`) on each vintage,
    and the fixed cost in each period a vintage is alive.

    params:
    - stock: columns `region`, `technology`, `stock` (capacity units, CEUD data year)
    - efficiency: columns `region`, `technology`, `vintage`, `fuel`, `efficiency`
    - capacity_factor: columns `region`, `technology`, `factor`
    - vintages: columns `technology`, `vintage`, `share`, see `existing_vintages`
      (shares adding up to less than 1 leave part of the stock out)
    - lifetime: columns `technology`, `lifetime` (years)
    - fixed_cost: columns `technology`, `cost` (M$ per unit of capacity and year);
      technologies without a positive cost have none
    - capacity_tolerance: minimum existing capacity of a (region, technology)
    """
    capacity = stock.merge(vintages, on="technology")
    capacity = capacity.assign(capacity=capacity["stock"] * capacity["share"])
    totals = capacity.groupby(["region", "technology"], as_index=False).agg(
        capacity=("capacity", "sum")
    )
    kept = totals.loc[
        (totals["capacity"] >= capacity_tolerance) & (totals["capacity"] > 0)
    ]
    dropped = totals.loc[(totals["capacity"] > 0) & ~totals.index.isin(kept.index)]
    for region, technology, total in zip(
        dropped["region"], dropped["technology"], dropped["capacity"]
    ):
        logger.info(
            f"{technology.value} left out of {region.short()}: existing capacity "
            + f"{total:.3g} below the tolerance {capacity_tolerance}"
        )
    capacity = capacity.merge(
        kept.loc[:, ["region", "technology"]], on=["region", "technology"]
    )
    capacity = capacity.loc[capacity["capacity"] > 0]
    # Capacity needs an efficiency to run (e.g. no energy use to weigh the
    # efficiencies of a technology's NRCan rows with)
    with_efficiency = efficiency.loc[:, ["region", "technology"]].drop_duplicates()
    no_efficiency = capacity.merge(
        with_efficiency, on=["region", "technology"], how="left", indicator=True
    )
    no_efficiency = no_efficiency.loc[no_efficiency["_merge"] == "left_only"]
    for region, technology in set(
        zip(no_efficiency["region"], no_efficiency["technology"])
    ):
        logger.warning(
            f"{technology.value} left out of {region.short()}: stock but no efficiency"
        )
    capacity = capacity.merge(with_efficiency, on=["region", "technology"])

    regions = pd.DataFrame({"region": provinces})
    with_vintages = capacity_factor.merge(
        vintages.loc[:, ["technology", "vintage"]], on="technology"
    )
    costs = fixed_cost.loc[fixed_cost["cost"] > 0].merge(
        vintages.loc[:, ["technology", "vintage"]], on="technology"
    )
    return ExistingTechnologyParameters(
        efficiency=efficiency,
        existing_capacity=capacity.loc[
            :, ["region", "technology", "vintage", "capacity"]
        ],
        capacity_factor=capacity_factor_band(
            with_vintages.loc[:, ["region", "technology", "vintage", "factor"]]
        ),
        lifetime=regions.merge(lifetime, how="cross"),
        fixed_cost=regions.merge(
            costs_while_alive(costs, lifetime, model_periods), how="cross"
        ),
        efficiency_notes=efficiency_notes,
        existing_capacity_notes=existing_capacity_notes,
        capacity_factor_notes=capacity_factor_notes,
        lifetime_notes=lifetime_notes,
        fixed_cost_notes=fixed_cost_notes,
    )

"""
New technologies from the AEO residential technology menu (lamps aside, see
`lighting`): efficiencies, costs and lifetimes by province and vintage. Nothing in
here touches the database.

Each province reads the equipment rows of its US census division (and the national
rows), valid in the data year of the vintage. Heating and cooling efficiencies are
the AEO's (EER times 0.293 to PJ/PJ); appliances, whose demands are appliances in
use, take the efficiency of their equivalent existing appliance improved by the AEO
new over base efficiency. Annual capacity factors are those of the equivalent
existing technology (`RESIDENTIAL_MODULE_BUGS.md`).
"""

import pandas as pd

from canoe.common import CANOEProvince
from canoe.common.census_divisions import USCensusDivision

from .end_uses import ResidentialEndUse
from .entities import NewTechnologyParameters
from .existing_stock import capacity_factor_band, costs_while_alive
from .space_cooling import eer_to_efficiency
from .technology_catalog import NewTechnology


def improved_efficiency(existing: float, new: float, base: float) -> float:
    """
    The efficiency of an existing appliance improved by the AEO new over base
    efficiency, whatever the direction of the AEO metric (energy factors grow with
    efficiency, kWh per cycle or year fall): the ratio is always at least 1.

    Examples
    --------
    >>> improved_efficiency(2.0, new=1.5, base=1.0), improved_efficiency(2.0, new=0.5, base=1.0)
    (3.0, 4.0)
    """
    return existing * (new / base if new >= base else base / new)


def new_technology_parameters(
    selected: dict[NewTechnology, list[ResidentialEndUse]],
    equipment: pd.DataFrame,
    classes: pd.DataFrame,
    census_divisions: dict[CANOEProvince, USCensusDivision],
    existing_capacity_factor: pd.DataFrame,
    existing_efficiency: pd.DataFrame,
    class_lifetimes: dict[str, float],
    currency_factor: float,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_years: dict[int, int],
) -> NewTechnologyParameters:
    """
    Parameters of the selected new technologies (not lamps), every model period a
    vintage.

    - Equipment rows: the AEO equipment of the technology, in the census division of
      the province or national (11), valid in the vintage's data year
      (`first_year <= year <= last_year`), in the order of the menu.
    - Investment cost: the first non-zero replacement cost, times 2 for heat pumps
      (the AEO splits their cost between heating and cooling).
    - Efficiency of each end use served: the first row of its AEO end use, times
      0.293 where the class's metric is EER; appliances: see `improved_efficiency`,
      with the efficiency of the first row and the class's base efficiency.
    - Fixed cost: the technology's (EIA), none if 0; lifetime: its AEO class's.
    - Annual capacity factor: that of the equivalent existing technology in the
      region, as a band (`existing_stock.capacity_factor_band`); none where it has
      none (the technology is then left out there, see
      `entities.build_new_technology`).

    params:
    - selected: technology -> end uses it serves, see
      `config.EndUsesConfig.new_technologies`
    - equipment, classes: see `loaders.AEOTechnologyMenu`
    - census_divisions: census division of each province
    - existing_capacity_factor: columns `region`, `technology` (`ExistingTechnology`),
      `factor`, see `existing_stock.EndUseStock.capacity_factor`
    - existing_efficiency: columns `region`, `technology`, `vintage`, `fuel`,
      `efficiency` of the existing appliances (every region, whatever their stock)
    - class_lifetimes: see `existing_stock.aeo_class_lifetimes`
    - currency_factor: USD of the AEO cost year to CAD of the model currency year
    - data_years: model period (vintage) -> year its data is read at
    """
    first_class = classes.drop_duplicates("equipment_class").set_index(
        "equipment_class"
    )
    efficiency_rows: list[
        tuple[CANOEProvince, NewTechnology, int, ResidentialEndUse, float]
    ] = []
    cost_rows: list[tuple[CANOEProvince, NewTechnology, int, float]] = []
    for technology, end_uses in selected.items():
        spec = technology.spec()
        if spec.lamp is not None:
            continue
        if spec.aeo_class is None or spec.aeo_equipment is None:
            raise ValueError(f"{technology.value} has no AEO class or equipment")
        cost_factor = spec.end_uses[0].cost_factor() * currency_factor
        rows_of_equipment = equipment.loc[equipment["equipment"] == spec.aeo_equipment]
        for province in provinces:
            division = census_divisions[province].get_aeo_number()
            own = rows_of_equipment.loc[
                rows_of_equipment["census_division"].isin([division, 11])
            ]
            for vintage in model_periods:
                year = data_years[vintage]
                valid = own.loc[
                    (own["first_year"] <= year) & (year <= own["last_year"])
                ]
                if valid.empty:
                    raise ValueError(
                        f"No AEO {spec.aeo_equipment} row for {province.short()} in {year}"
                    )
                costs = valid.loc[valid["replacement_cost"] != 0, "replacement_cost"]
                cost = float(costs.iloc[0]) * (2 if len(spec.end_uses) == 2 else 1)
                cost_rows.append((province, technology, vintage, cost * cost_factor))
                for end_use in end_uses:
                    if end_use.is_appliance():
                        equivalent = spec.equivalents[end_use]
                        existing = existing_efficiency.loc[
                            existing_efficiency["region"].isin([province])
                            & existing_efficiency["technology"].isin([equivalent]),
                            "efficiency",
                        ]
                        if existing.empty:
                            continue
                        efficiency = improved_efficiency(
                            float(existing.iloc[0]),
                            new=float(valid["efficiency"].iloc[0]),
                            base=float(
                                first_class.loc[spec.aeo_class, "base_efficiency"]
                            ),
                        )
                    else:
                        aeo_end_use = end_use.get_aeo_end_use()
                        of_end_use = valid.loc[valid["end_use"] == aeo_end_use]
                        metric = classes.loc[
                            (classes["equipment_class"] == spec.aeo_class)
                            & (classes["end_use"] == aeo_end_use),
                            "efficiency_metric",
                        ]
                        efficiency = float(of_end_use["efficiency"].iloc[0]) * (
                            eer_to_efficiency()
                            if len(metric) and metric.iloc[0] == "EER"
                            else 1.0
                        )
                    efficiency_rows.append(
                        (province, technology, vintage, end_use, efficiency)
                    )

    efficiency = pd.DataFrame(
        efficiency_rows,
        columns=["region", "technology", "vintage", "end_use", "efficiency"],
    )
    investment_cost = pd.DataFrame(
        cost_rows, columns=["region", "technology", "vintage", "cost"]
    )
    technologies = [t for t in selected if t.spec().lamp is None]
    lifetime = pd.DataFrame(
        {
            "technology": technologies,
            "lifetime": [
                class_lifetimes[str(t.spec().aeo_class)] for t in technologies
            ],
        }
    )
    fixed_cost = pd.DataFrame(
        [
            (
                t,
                float(t.spec().fixed_cost or 0)
                * t.spec().end_uses[0].cost_factor()
                * currency_factor,
            )
            for t in technologies
        ],
        columns=["technology", "cost"],
    )
    fixed_cost = fixed_cost.loc[fixed_cost["cost"] > 0]
    fixed_cost = costs_while_alive(
        investment_cost.loc[:, ["region", "technology", "vintage"]].merge(
            fixed_cost, on="technology"
        ),
        lifetime,
        model_periods,
    )

    # Capacity factor of the equivalent existing technology of each end use served
    equivalents = pd.DataFrame(
        [
            (t, end_use, t.spec().equivalents[end_use])
            for t, end_uses in selected.items()
            if t.spec().lamp is None
            for end_use in end_uses
        ],
        columns=["technology", "end_use", "equivalent"],
    )
    capacity_factor = equivalents.merge(
        existing_capacity_factor.rename(columns={"technology": "equivalent"}),
        on="equivalent",
    ).merge(pd.DataFrame({"vintage": model_periods}), how="cross")

    regions = pd.DataFrame({"region": provinces})
    return NewTechnologyParameters(
        efficiency=efficiency,
        investment_cost=investment_cost,
        fixed_cost=fixed_cost.loc[
            :, ["region", "technology", "vintage", "period", "cost"]
        ],
        lifetime=regions.merge(lifetime, how="cross"),
        lifetime_process=pd.DataFrame(
            columns=["region", "technology", "vintage", "lifetime"]
        ),
        capacity_factor=capacity_factor_band(
            capacity_factor.loc[
                :, ["region", "technology", "vintage", "end_use", "factor"]
            ]
        ),
        efficiency_notes="AEO efficiency of the equipment in the vintage's data year "
        + "(EER times 0.293 to PJ/PJ); appliances: efficiency of the equivalent "
        + "existing appliance times the AEO new over base efficiency",
        investment_cost_notes="AEO replacement cost of the equipment in the vintage's "
        + "data year (heat pumps: times 2, the AEO splits it between heating and "
        + "cooling)",
        fixed_cost_notes="Fixed O&M cost (EIA, 2023, Updated Buildings Sector "
        + "Appliance and Equipment Costs and Efficiency)",
        lifetime_notes="Mean of the Weibull distribution of the AEO class",
        lifetime_process_notes="",
        capacity_factor_notes="Annual capacity factor of the equivalent existing "
        + "technology; lower bound 95% of it",
    )

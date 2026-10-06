"""
Water heating: the existing water heaters of the NRCan CEUD (tables 10 and 28) and
the demand they serve. Nothing in here touches the database.

NRCan has no water heater efficiencies: each takes the base efficiency of the AEO
class of its equivalent new technology.
"""

import pandas as pd

from canoe.common import CANOEProvince

from .end_uses import ResidentialEndUse
from .existing_stock import EndUseStock, existing_technology_parameters
from .technology_catalog import ExistingTechnology


def water_heating_stock(
    energy_use: pd.DataFrame,
    stock: pd.DataFrame,
    aeo_classes: pd.DataFrame,
    vintages: pd.DataFrame,
    lifetime: pd.DataFrame,
    fixed_cost: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    capacity_tolerance: float,
    ceud_data_year: int,
) -> EndUseStock:
    """
    The existing water heating technologies and the base-year demand.

    - Efficiency: the AEO base efficiency of the class of the equivalent new
      technology (the wood stove's for wood water heaters), in every region.
    - Existing capacity: the stock (kunit) of the energy source ("steam" unused).
    - Hot water delivered: energy use times efficiency.
    - Annual capacity factor: hot water / stock (capacity to activity 1), where there
      is stock.
    - Demand: the hot water of every energy source.

    params:
    - energy_use, stock: CEUD tables 10 and 28 (`source` column), see
      `ceud.ResidentialCEUD`
    - aeo_classes: see `loaders.AEOTechnologyMenu.classes`
    - vintages, lifetime, fixed_cost: of the existing technologies, see
      `existing_stock.existing_technology_parameters`
    """
    technologies = [
        t
        for t in ExistingTechnology
        if t.spec().end_use == ResidentialEndUse.WaterHeating
    ]
    base_efficiency = dict(
        zip(
            aeo_classes.drop_duplicates("equipment_class")["equipment_class"],
            aeo_classes.drop_duplicates("equipment_class")["base_efficiency"],
        )
    )

    def class_of(technology: ExistingTechnology) -> str:
        equivalent = technology.spec().new_equivalent
        aeo_class = equivalent.spec().aeo_class if equivalent is not None else None
        if aeo_class is None:
            raise ValueError(f"{technology.value} has no AEO class")
        return aeo_class

    source_of = {t.spec().nrcan_rows[0]: t for t in technologies}
    efficiency_of = {t: base_efficiency[class_of(t)] for t in technologies}

    def by_technology(df: pd.DataFrame) -> pd.DataFrame:
        rows = df.loc[df["source"].isin(list(source_of))]
        return rows.assign(technology=[source_of[s] for s in rows["source"]]).rename(
            columns={"province": "region"}
        )

    hot_water = by_technology(energy_use)
    hot_water = hot_water.assign(
        hot_water=hot_water["energy_use"]
        * [efficiency_of[t] for t in hot_water["technology"]]
    )
    technology_stock = by_technology(stock)
    with_stock = technology_stock.merge(
        hot_water.loc[:, ["region", "technology", "hot_water"]],
        on=["region", "technology"],
    )
    with_stock = with_stock.loc[with_stock["stock"] > 0]
    capacity_factor = with_stock.assign(
        factor=with_stock["hot_water"] / with_stock["stock"]
    )

    efficiency = pd.DataFrame(
        [
            (region, t, t.spec().fuels[0], efficiency_of[t])
            for region in provinces
            for t in technologies
        ],
        columns=["region", "technology", "fuel", "efficiency"],
    ).merge(vintages.loc[:, ["technology", "vintage"]], on="technology")

    base_demand = (
        hot_water.groupby("region", as_index=False)
        .agg(demand=("hot_water", "sum"))
        .assign(end_use=ResidentialEndUse.WaterHeating)
    )
    return EndUseStock(
        technologies=technologies,
        parameters=existing_technology_parameters(
            stock=technology_stock.loc[:, ["region", "technology", "stock"]],
            efficiency=efficiency.loc[
                :, ["region", "technology", "vintage", "fuel", "efficiency"]
            ],
            capacity_factor=capacity_factor.loc[:, ["region", "technology", "factor"]],
            vintages=vintages,
            lifetime=lifetime,
            fixed_cost=fixed_cost,
            provinces=provinces,
            model_periods=model_periods,
            capacity_tolerance=capacity_tolerance,
            efficiency_notes="AEO base efficiency of the class of the equivalent new "
            + "technology (NRCan has no water heater efficiencies)",
            existing_capacity_notes=f"{ceud_data_year} stock (NRCan CEUD table 28) "
            + "standing in the first model period, spread evenly over the vintages "
            + "alive then",
            capacity_factor_notes="Annual utilisation of the stock: energy use (NRCan "
            + f"CEUD table 10, {ceud_data_year}) times efficiency over stock (table "
            + "28); lower bound 95% of it",
            lifetime_notes="Mean of the Weibull distribution of the AEO class of the "
            + "equivalent new technology",
            fixed_cost_notes="Fixed cost of the equivalent new technology (EIA, 2023)",
        ),
        base_demand=base_demand.loc[:, ["region", "end_use", "demand"]],
        demand_notes="Energy use of each energy source (NRCan CEUD table 10, "
        + f"{ceud_data_year}) times the AEO base efficiency of its water heaters. "
        + "Indexed to the demand driver",
        capacity_factor=capacity_factor.loc[:, ["region", "technology", "factor"]],
    )

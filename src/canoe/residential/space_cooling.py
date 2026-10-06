"""
Space cooling: the existing room and central air conditioners of the NRCan CEUD
(tables 4 and 27) and the demand they serve. Nothing in here touches the database.

NRCan gives cooling efficiencies as EER (room) and SEER (central units), in kBtu of
cooling per kWh of electricity: times 0.293 they are PJ of cooling per PJ.
"""

import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince

from .end_uses import ResidentialEndUse
from .existing_stock import EndUseStock, existing_technology_parameters
from .technology_catalog import ExistingTechnology


def eer_to_efficiency() -> float:
    """PJ of cooling per PJ of electricity in one kBtu/kWh (EER, SEER)"""
    return 0.293


def space_cooling_stock(
    energy_use: pd.DataFrame,
    stock: pd.DataFrame,
    efficiencies: pd.DataFrame,
    vintages: pd.DataFrame,
    lifetime: pd.DataFrame,
    fixed_cost: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    capacity_tolerance: float,
    ceud_data_year: int,
) -> EndUseStock:
    """
    The existing space cooling technologies and the base-year demand.

    - Existing capacity: the stock (kunit) of the system type.
    - Efficiency of each vintage: NRCan's stock efficiency of the year of the vintage
      (the last year of the table for newer vintages), see
      `RESIDENTIAL_MODULE_BUGS.md`.
    - Cooling delivered: energy use times the stock efficiency of the data year.
    - Annual capacity factor: cooling / stock (capacity to activity 1), where there
      is stock.
    - Demand: the cooling of both system types.

    params:
    - energy_use, stock, efficiencies: CEUD tables 4 and 27, see
      `ceud.ResidentialCEUD`
    - vintages, lifetime, fixed_cost: of the existing technologies, see
      `existing_stock.existing_technology_parameters`
    """
    technologies = [
        t
        for t in ExistingTechnology
        if t.spec().end_use == ResidentialEndUse.SpaceCooling
    ]
    system_of = {t: t.spec().nrcan_rows[0] for t in technologies}
    stock_efficiency = efficiencies.loc[efficiencies["kind"] == "stock"]
    stock_efficiency = stock_efficiency.assign(
        efficiency=stock_efficiency["efficiency"] * eer_to_efficiency()
    )

    cooling = energy_use.merge(
        stock_efficiency.loc[stock_efficiency["year"] == ceud_data_year],
        on=["province", "system"],
        validate="one_to_one",
    )
    cooling = cooling.assign(cooling=cooling["energy_use"] * cooling["efficiency"])

    def by_technology(df: pd.DataFrame) -> pd.DataFrame:
        technology_of = {system: t for t, system in system_of.items()}
        rows = df.loc[df["system"].isin(list(technology_of))]
        return rows.assign(
            technology=[technology_of[s] for s in rows["system"]]
        ).rename(columns={"province": "region"})

    technology_stock = by_technology(stock)
    with_stock = technology_stock.merge(
        by_technology(cooling).loc[:, ["region", "technology", "cooling"]],
        on=["region", "technology"],
    )
    with_stock = with_stock.loc[with_stock["stock"] > 0]
    capacity_factor = with_stock.assign(
        factor=with_stock["cooling"] / with_stock["stock"]
    )

    # Efficiency of each vintage: that of its year, or of the last year of the table
    last_year = int(stock_efficiency["year"].max())
    efficiency = by_technology(stock_efficiency).merge(
        vintages.loc[:, ["technology", "vintage"]].assign(
            year=vintages["vintage"].clip(upper=last_year)
        ),
        on=["technology", "year"],
    )

    base_demand = (
        cooling.rename(columns={"province": "region"})
        .groupby("region", as_index=False)
        .agg(demand=("cooling", "sum"))
        .assign(end_use=ResidentialEndUse.SpaceCooling)
    )
    return EndUseStock(
        technologies=technologies,
        parameters=existing_technology_parameters(
            stock=technology_stock.loc[:, ["region", "technology", "stock"]],
            efficiency=efficiency.assign(fuel=CANOEFuel.Electricity).loc[
                :, ["region", "technology", "vintage", "fuel", "efficiency"]
            ],
            capacity_factor=capacity_factor.loc[:, ["region", "technology", "factor"]],
            vintages=vintages,
            lifetime=lifetime,
            fixed_cost=fixed_cost,
            provinces=provinces,
            model_periods=model_periods,
            capacity_tolerance=capacity_tolerance,
            efficiency_notes="NRCan stock efficiency (EER, SEER) of the year of the "
            + "vintage, or of the last year for newer vintages (CEUD table 27), "
            + "times 0.293 (kBtu/kWh to PJ/PJ)",
            existing_capacity_notes=f"{ceud_data_year} stock (NRCan CEUD table 27) "
            + "standing in the first model period, spread evenly over the vintages "
            + "alive then",
            capacity_factor_notes="Annual utilisation of the stock: energy use times "
            + "stock efficiency over stock (NRCan CEUD tables 4 and 27, "
            + f"{ceud_data_year}); lower bound 95% of it",
            lifetime_notes="Mean of the Weibull distribution of the AEO class of the "
            + "equivalent new technology",
            fixed_cost_notes="Fixed cost of the equivalent new technology (EIA, 2023)",
        ),
        base_demand=base_demand.loc[:, ["region", "end_use", "demand"]],
        demand_notes="Energy use times stock efficiency of each cooling system type "
        + f"(NRCan CEUD tables 4 and 27, {ceud_data_year}). Indexed to the demand "
        + "driver",
        capacity_factor=capacity_factor.loc[:, ["region", "technology", "factor"]],
    )

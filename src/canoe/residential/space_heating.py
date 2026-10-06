"""
Space heating: the existing heating systems of the NRCan CEUD (tables 8, 21 and 26)
and the demand they serve. Nothing in here touches the database.

The heat delivered by each NRCan system type is its energy use times its stock
efficiency; the demand is the heat of all the systems. Dual systems burn two fuels in
unknown proportions: their heat is computed with the efficiency of the first fuel of
their name (wood for wood/electric), and the model chooses their fuel mix.
"""

import pandas as pd

from canoe.common import CANOEProvince

from .ceud import ceud_fuel
from .end_uses import ResidentialEndUse
from .existing_stock import EndUseStock, existing_technology_parameters
from .technology_catalog import ExistingTechnology


def system_heat(energy_use: pd.DataFrame, efficiencies: pd.DataFrame) -> pd.DataFrame:
    """
    Heat delivered (PJ) by each heating system type: its energy use times its stock
    efficiency, that of the first fuel of the name for dual systems.

    params:
    - energy_use: columns `province`, `system`, `energy_use` (PJ), CEUD table 8
    - efficiencies: columns `province`, `system`, `fuel`, `efficiency`, CEUD table
      26 (see `ceud.ResidentialCEUD`)

    Returns province, system, heat
    """
    first_fuel = efficiencies["system"].str.split("/").str[0]
    own = efficiencies.loc[
        efficiencies["fuel"].isna() | (efficiencies["fuel"] == first_fuel)
    ]
    heat = energy_use.merge(
        own[["province", "system", "efficiency"]],
        on=["province", "system"],
        validate="one_to_one",
    )
    return heat.assign(heat=heat["energy_use"] * heat["efficiency"])[
        ["province", "system", "heat"]
    ]


def system_efficiencies(
    technology: ExistingTechnology,
    energy_use: pd.DataFrame,
    efficiencies: pd.DataFrame,
) -> pd.DataFrame:
    """
    Efficiency of `technology` by province and fuel: the efficiency of its NRCan row,
    the efficiencies of its rows weighted by their energy use (none where they use
    no energy), or, for dual systems, the efficiency of each fuel.

    Returns region, technology, fuel, efficiency
    """
    spec = technology.spec()
    rows = efficiencies.loc[efficiencies["system"].isin(spec.nrcan_rows)]
    if len(spec.fuels) > 1:
        return pd.DataFrame(
            {
                "region": rows["province"],
                "technology": technology,
                "fuel": [ceud_fuel(f) for f in rows["fuel"]],
                "efficiency": rows["efficiency"],
            }
        ).reset_index(drop=True)
    weighted = rows.merge(energy_use, on=["province", "system"])
    weighted = weighted.assign(weighted=weighted["efficiency"] * weighted["energy_use"])
    by_province = weighted.groupby("province", as_index=False)[
        ["weighted", "energy_use"]
    ].sum()
    if len(spec.nrcan_rows) > 1:
        by_province = by_province.loc[by_province["energy_use"] > 0]
        efficiency = by_province["weighted"] / by_province["energy_use"]
    else:
        efficiency = rows.set_index("province").loc[
            by_province["province"], "efficiency"
        ]
    return pd.DataFrame(
        {
            "region": by_province["province"].to_numpy(),
            "technology": technology,
            "fuel": spec.fuels[0],
            "efficiency": efficiency.to_numpy(),
        }
    )


def space_heating_stock(
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
    The existing space heating technologies and the base-year demand.

    - Existing capacity: the stock (kunit) of the technology's NRCan rows.
    - Efficiency: see `system_efficiencies`, the same for every vintage.
    - Annual capacity factor: heat / stock (capacity to activity 1), where there is
      stock.
    - Demand: the heat of every system type (see `system_heat`).

    params:
    - energy_use, stock, efficiencies: CEUD tables 8, 21 and 26, see
      `ceud.ResidentialCEUD`
    - vintages, lifetime, fixed_cost: of the existing technologies, see
      `existing_stock.existing_technology_parameters`
    """
    technologies = [
        t
        for t in ExistingTechnology
        if t.spec().end_use == ResidentialEndUse.SpaceHeating
    ]
    heat = system_heat(energy_use, efficiencies)

    def by_technology(df: pd.DataFrame, value: str) -> pd.DataFrame:
        """`value` of the NRCan rows of each technology, summed"""
        rows = [
            df.loc[df["system"].isin(t.spec().nrcan_rows)]
            .groupby("province", as_index=False)[value]
            .sum()
            .assign(technology=t)
            for t in technologies
        ]
        return pd.concat(rows, ignore_index=True).rename(columns={"province": "region"})

    technology_stock = by_technology(stock, "stock")
    technology_heat = by_technology(heat, "heat")
    with_stock = technology_stock.merge(technology_heat, on=["region", "technology"])
    with_stock = with_stock.loc[with_stock["stock"] > 0]
    capacity_factor = with_stock.assign(factor=with_stock["heat"] / with_stock["stock"])

    efficiency = pd.concat(
        [system_efficiencies(t, energy_use, efficiencies) for t in technologies],
        ignore_index=True,
    ).merge(vintages[["technology", "vintage"]], on="technology")

    base_demand = (
        heat.groupby("province", as_index=False)["heat"]
        .sum()
        .rename(columns={"province": "region", "heat": "demand"})
        .assign(end_use=ResidentialEndUse.SpaceHeating)
    )
    return EndUseStock(
        technologies=technologies,
        parameters=existing_technology_parameters(
            stock=technology_stock,
            efficiency=efficiency[
                ["region", "technology", "vintage", "fuel", "efficiency"]
            ],
            capacity_factor=capacity_factor[["region", "technology", "factor"]],
            vintages=vintages,
            lifetime=lifetime,
            fixed_cost=fixed_cost,
            provinces=provinces,
            model_periods=model_periods,
            capacity_tolerance=capacity_tolerance,
            efficiency_notes="Stock efficiency of the NRCan heating system types "
            + f"(CEUD table 26, {ceud_data_year}), weighted by their energy use "
            + "(table 8) where several; dual systems: the efficiency of each fuel",
            existing_capacity_notes=f"{ceud_data_year} stock (NRCan CEUD table 21) "
            + "standing in the first model period, spread evenly over the vintages "
            + "alive then",
            capacity_factor_notes="Annual utilisation of the stock: energy use times "
            + f"efficiency over stock (NRCan CEUD tables 8, 21, 26, {ceud_data_year}); "
            + "lower bound 95% of it",
            lifetime_notes="Mean of the Weibull distribution of the AEO class of the "
            + "equivalent new technology",
            fixed_cost_notes="Fixed cost of the equivalent new technology (EIA, 2023)",
        ),
        base_demand=base_demand[["region", "end_use", "demand"]],
        demand_notes="Energy use times stock efficiency of each heating system type "
        + f"(NRCan CEUD tables 8 and 26, {ceud_data_year}); dual systems with the "
        + "efficiency of their first fuel. Indexed to the demand driver",
        capacity_factor=capacity_factor[["region", "technology", "factor"]],
    )

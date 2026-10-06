"""
Appliances: the existing appliance stock of the NRCan CEUD (tables 13 and 31) and
the demands it serves, in appliances in use (Munity). Nothing in here touches the
database.

Appliances run an arbitrary share of the year (`annual_capacity_factor`, see
`RESIDENTIAL_MODULE_BUGS.md`): the demand of each appliance end use is its stock
times that factor, and an appliance's efficiency is that activity over its energy
use. Clothes dryers and ranges come in two fuels whose energy use NRCan does not
split by province: their efficiency is the factor over the unit energy consumption
of the stock (NRCan Energy Use Data Handbook).
"""

from dataclasses import dataclass

import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince

from .ceud import ceud_fuel
from .end_uses import ResidentialEndUse
from .existing_stock import EndUseStock, existing_technology_parameters
from .technology_catalog import ExistingTechnology


def kwh_to_pj() -> float:
    """PJ in a kWh"""
    return 3.6e-9


@dataclass(frozen=True)
class ApplianceStock:
    """
    The existing appliances (`stock`, other appliances excluded) and the efficiency
    of other electrical appliances and devices (`R_APP_OTH`, unlimited capacity):
    columns `region`, `efficiency` (Munity/PJ).
    """

    stock: EndUseStock
    other_appliances_efficiency: pd.DataFrame


def appliance_stock(
    energy_use: pd.DataFrame,
    stock: pd.DataFrame,
    unit_consumption: pd.DataFrame | None,
    annual_capacity_factor: float,
    vintages: pd.DataFrame,
    lifetime: pd.DataFrame,
    fixed_cost: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    capacity_tolerance: float,
    ceud_data_year: int,
) -> ApplianceStock:
    """
    The existing appliance technologies, other appliances and the base-year demands.

    - Existing capacity: the stock (Munit) of the appliance and fuel.
    - Demand of each end use: the stock of its appliances (other appliances
      included) times `annual_capacity_factor`.
    - Efficiency (Munity/PJ): stock times `annual_capacity_factor` over energy use;
      clothes dryers and ranges (both fuels): `annual_capacity_factor` over the
      handbook unit energy consumption.
    - Annual capacity factor: `annual_capacity_factor`, in every region.

    params:
    - energy_use, stock: CEUD tables 13 and 31 (`appliance` column, and `fuel` for
      the stock), see `ceud.ResidentialCEUD`
    - unit_consumption: columns `appliance`, `fuel`, `unit_consumption` (kWh/year),
      see `loaders.get_handbook_appliance_consumption`; None if neither clothes
      dryers nor ranges are modelled
    - vintages, lifetime, fixed_cost: of the existing technologies, see
      `existing_stock.existing_technology_parameters`
    """
    appliances = [
        t
        for t in ExistingTechnology
        if t.spec().end_use.is_appliance()
        and t.spec().end_use != ResidentialEndUse.OtherAppliances
    ]
    two_fuels = (ResidentialEndUse.ClothesDryers, ResidentialEndUse.CookingRanges)
    with_other = [*appliances, ExistingTechnology.OtherAppliances]

    # Stock (Munit) of each technology: its NRCan row of its fuel
    stock_rows = stock.assign(fuel=[ceud_fuel(f) for f in stock["fuel"]])
    technology_stock = pd.concat(
        [
            stock_rows.loc[
                stock_rows["appliance"].isin(t.spec().nrcan_rows)
                & stock_rows["fuel"].isin(t.spec().fuels)
            ].assign(technology=t)
            for t in with_other
        ],
        ignore_index=True,
    ).rename(columns={"province": "region"})
    technology_stock = technology_stock.assign(stock=technology_stock["stock"] / 1000)
    end_use_of = {t: t.spec().end_use for t in with_other}
    activity = technology_stock.assign(
        end_use=[end_use_of[t] for t in technology_stock["technology"]],
        activity=technology_stock["stock"] * annual_capacity_factor,
    )

    # Efficiency: activity over energy use, or over the unit consumption of the
    # stock for the end uses with two fuels
    single_fuel = activity.loc[~activity["end_use"].isin(two_fuels)].merge(
        energy_use.rename(columns={"province": "region"}),
        left_on=["region", "appliance"],
        right_on=["region", "appliance"],
    )
    efficiency = single_fuel.assign(
        efficiency=single_fuel["activity"] / single_fuel["energy_use"]
    ).loc[:, ["region", "technology", "fuel", "efficiency"]]
    two_fuel_technologies = [t for t in appliances if t.spec().end_use in two_fuels]
    if two_fuel_technologies:
        if unit_consumption is None:
            raise ValueError(
                "Clothes dryers or ranges need the handbook unit energy consumption"
            )
        consumption = unit_consumption.assign(
            fuel=[ceud_fuel(f) for f in unit_consumption["fuel"]]
        )
        rows: list[tuple[CANOEProvince, ExistingTechnology, CANOEFuel, float]] = []
        for t in two_fuel_technologies:
            spec = t.spec()
            uec = consumption.loc[
                consumption["appliance"].isin(spec.nrcan_rows)
                & consumption["fuel"].isin(spec.fuels),
                "unit_consumption",
            ]
            if len(uec) != 1:
                raise ValueError(f"No single unit energy consumption for {t.value}")
            # Munity per PJ: appliances in use (Munit x factor) per PJ they consume
            value = annual_capacity_factor / (float(uec.iloc[0]) * kwh_to_pj() * 1e6)
            rows.extend((region, t, spec.fuels[0], value) for region in provinces)
        efficiency = pd.concat(
            [
                efficiency,
                pd.DataFrame(
                    rows, columns=["region", "technology", "fuel", "efficiency"]
                ),
            ],
            ignore_index=True,
        )

    other = efficiency.loc[
        efficiency["technology"].isin([ExistingTechnology.OtherAppliances])
    ]
    efficiency = efficiency.loc[efficiency["technology"].isin(appliances)].merge(
        vintages.loc[:, ["technology", "vintage"]], on="technology"
    )
    capacity_factor = pd.DataFrame(
        [
            (region, t, annual_capacity_factor)
            for region in provinces
            for t in appliances
        ],
        columns=["region", "technology", "factor"],
    )
    base_demand = activity.groupby(["region", "end_use"], as_index=False).agg(
        demand=("activity", "sum")
    )
    appliance_rows = technology_stock["technology"].isin(appliances)
    return ApplianceStock(
        stock=EndUseStock(
            technologies=appliances,
            parameters=existing_technology_parameters(
                stock=technology_stock.loc[
                    appliance_rows, ["region", "technology", "stock"]
                ],
                efficiency=efficiency.loc[
                    :, ["region", "technology", "vintage", "fuel", "efficiency"]
                ],
                capacity_factor=capacity_factor,
                vintages=vintages,
                lifetime=lifetime,
                fixed_cost=fixed_cost,
                provinces=provinces,
                model_periods=model_periods,
                capacity_tolerance=capacity_tolerance,
                efficiency_notes="Appliances in use (stock times the annual capacity "
                + "factor) over energy use (NRCan CEUD tables 13 and 31, "
                + f"{ceud_data_year}); clothes dryers and ranges: annual capacity "
                + "factor over the unit energy consumption of the stock (NRCan "
                + "Energy Use Data Handbook, 2021)",
                existing_capacity_notes=f"{ceud_data_year} stock (NRCan CEUD table "
                + "31) standing in the first model period, spread evenly over the "
                + "vintages alive then",
                capacity_factor_notes="Arbitrary annual capacity factor, so the "
                + "existing stock can meet the peak demand; lower bound 95% of it",
                lifetime_notes="Mean of the Weibull distribution of the AEO class of "
                + "the equivalent new technology",
                fixed_cost_notes="Fixed cost of the equivalent new technology (EIA, "
                + "2023)",
            ),
            base_demand=base_demand.loc[:, ["region", "end_use", "demand"]],
            demand_notes=f"Stock (NRCan CEUD table 31, {ceud_data_year}) times an "
            + f"arbitrary annual capacity factor of {annual_capacity_factor}, so the "
            + "existing stock can meet the peak demand. Indexed to the demand driver",
            capacity_factor=capacity_factor,
        ),
        other_appliances_efficiency=other.loc[:, ["region", "efficiency"]].reset_index(
            drop=True
        ),
    )

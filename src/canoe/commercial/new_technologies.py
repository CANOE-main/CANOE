"""
New (buildable) space heating and cooling technologies.

Takes the AEO parameters of the selected new technologies (see `technology_catalog`)
and turns them into `TechnologyEntity` objects, one per technology. A technology
serving both space heating and space cooling (e.g. a heat pump) is a single technology
with one output per end use. Nothing in here touches the database; the caller decides
when to `.build()` the returned entities.

A technology is only offered in a province for the end uses with existing-stock data for
its fuel (the annual capacity factor comes from there), as in the previous version.
"""

from typing import Any

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode
from loguru import logger

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import FuelCommodityEntity
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_commodity_name,
    get_fuel_commodity_in_sector,
)

from .end_uses import CommercialEndUse
from .technology_catalog import NEW_TECHNOLOGIES, NewTechnology

_END_USE_TAGS: dict[tuple[CommercialEndUse, ...], tuple[str, str]] = {
    (CommercialEndUse.SpaceHeating,): ("SPH", "space heating"),
    (CommercialEndUse.SpaceCooling,): ("SPC", "space cooling"),
    (CommercialEndUse.SpaceHeating, CommercialEndUse.SpaceCooling): (
        "SPHC",
        "space heating/cooling",
    ),
}


def build_new_technologies(
    new_technologies: dict[NewTechnology, list[CommercialEndUse]],
    new_tech_params: pd.DataFrame,
    annual_capacity_factors: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> list[TechnologyEntity]:
    """
    Build one technology entity per selected new technology.

    params:
    - new_technologies: technology -> end uses it serves (space heating first), see
      `EndUsesConfig.new_technologies`
    - new_tech_params: one row per (technology, end_use, province), see
      `load_new_technology_params`. Not modified.
    - annual_capacity_factors: existing-stock annual capacity factors, one row per
      (province, end_use, fuel) with columns `province`, `end_use` (full name), `fuel`,
      `acf`. A technology serves an end use in a province only if it has a row here.
    - model_periods: vintages the technologies can be built in, and periods for fixed costs

    Technology-level parameters (lifetime, costs) come from the first end use the
    technology serves in each province (space heating before space cooling), as in the
    previous version; a warning lists the provinces where the other end uses disagree.
    Technologies served in no province are left out, with a warning.
    """
    technologies: list[TechnologyEntity] = []
    for technology, end_uses in new_technologies.items():
        entity = _new_technology(
            technology,
            end_uses,
            new_tech_params[new_tech_params["technology"].isin([technology])],  # pyright: ignore[reportArgumentType]
            annual_capacity_factors,
            provinces,
            model_periods,
            data_id,
        )
        if entity is None:
            logger.warning(
                f"New technology `{technology.value}` has no province with existing-stock "
                + "data for its fuel and end uses, skipping"
            )
            continue
        technologies.append(entity)
    return technologies


def new_technology_fuel_commodities(
    new_technologies: dict[NewTechnology, list[CommercialEndUse]],
    data_id: DatasetIdentifier,
) -> list[FuelCommodityEntity]:
    """Fuel commodities the selected new technologies take as input, one per fuel"""
    fuels = list(dict.fromkeys(NEW_TECHNOLOGIES[t].fuel for t in new_technologies))
    return [
        FuelCommodityEntity(
            sector=CANOESector.Commercial,
            fuel=fuel,
            flag=CommodityTypeCode.P
            if fuel == CANOEFuel.Electricity
            else CommodityTypeCode.A,
            data_id=data_id,
        )
        for fuel in fuels
    ]


def _new_technology(
    technology: NewTechnology,
    end_uses: list[CommercialEndUse],
    params: pd.DataFrame,
    annual_capacity_factors: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> TechnologyEntity | None:
    """
    `params`: rows of `new_tech_params` for `technology`.
    None if the technology serves no end use in any province.
    """
    spec = NEW_TECHNOLOGIES[technology]
    tag, end_use_label = _END_USE_TAGS[tuple(end_uses)]

    # Rows (technology, end_use, province) where the end use is served: those with an
    # existing-stock annual capacity factor for the technology's fuel.
    # NOTE: fuel and end use columns are filtered with `isin`: with pandas 3 `str`
    # columns, `== CANOEFuel.X` compares against the member name and never matches.
    acf = annual_capacity_factors[annual_capacity_factors["fuel"].isin([spec.fuel])][
        ["province", "end_use", "acf"]
    ]
    served: Any = params.assign(
        end_use_name=params["end_use"].map(lambda eu: eu.get_full_name())  # pyright: ignore[reportUnknownLambdaType]
    ).merge(
        acf.rename(columns={"end_use": "end_use_name"}),  # pyright: ignore[reportCallIssue, reportAttributeAccessIssue]
        on=["province", "end_use_name"],
    )
    if served.empty:
        return None
    served = served.rename(columns={"province": "region"})

    # Technology-level parameters: first served end use in each province
    served["end_use_order"] = served["end_use"].map(end_uses.index)
    served = served.sort_values(["region", "end_use_order"])
    technology_params = served.groupby("region", sort=False).first().reset_index()
    _warn_on_disagreeing_end_uses(technology, served)

    aeo_technology = spec.aeo_technologies[end_uses[0]]
    vintages = model_periods
    by_vintage = technology_params.merge(
        pd.DataFrame({"vintage": vintages}), how="cross"
    )

    lifetimes = RegionalValuesArray(region=provinces).fill_from_df(
        technology_params, value_col="life"
    )
    capacity_to_activity = RegionalValuesArray(region=provinces).fill_from_df(
        technology_params.assign(c2a=1.0), value_col="c2a"
    )
    investment_costs = RegionVintageArray(
        region=provinces, vintage=vintages
    ).fill_from_df(by_vintage, value_col="investment_cost")
    # Rounded like the written lifetimes, so costs stop when the vintage retires
    rounded_lifetimes = RegionalValuesArray(region=provinces).fill_from_df(
        technology_params.assign(life=technology_params["life"].round()),
        value_col="life",
    )
    fixed_costs = (
        RegionVintagePeriodArray(
            region=provinces, vintage=vintages, period=model_periods
        )
        .fill_from_df(by_vintage, dims=["region", "vintage"], value_col="fixed_cost")
        .mask_out_period_before_vintage()
        .mask_out_after_life(rounded_lifetimes)
    )

    entity = (
        TechnologyEntity(
            name=f"{CANOESector.Commercial.get_tag()}_{tag}_{spec.code}-{TechnologyCapacityScope.New.value}",
            output_commodity=_demand_commodity(end_uses[0]),
            data_id=data_id,
            description=f"{end_use_label} {technology.value} - new",
            sector=CANOESector.Commercial,
        )
        .set_annual()
        .with_lifetime(
            lifetimes,
            notes=f"Rounded life from AEO CDM ktekx technology menu for technology {aeo_technology} (AEO, {2022})",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=1, tech=2, time=3),
        )
        .with_capacity_to_activity(
            capacity_to_activity,
            notes="Capacity is in PJ/y and activity is in PJ so 1",
            units="1",
        )
        .with_investment_cost(
            investment_costs,
            notes=f"Capcst from AEO CDM ktekx technology menu for technology {aeo_technology} (AEO, {2022})",
            units="M$/PJ/y",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=1, tech=2, time=2),
        )
        .with_fixed_cost(
            fixed_costs,
            notes=f"Maintcst from AEO CDM ktekx technology menu for technology {aeo_technology} (AEO, {2022})",
            units="M$/PJ",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=1, tech=2, time=2),
        )
    )

    # One output per served end use
    input_commodity = get_fuel_commodity_in_sector(CANOESector.Commercial, spec.fuel)
    for end_use in end_uses:
        end_use_rows = served[served["end_use"].isin([end_use])]
        if end_use_rows.empty:
            continue
        end_use_by_vintage = end_use_rows.merge(
            pd.DataFrame({"vintage": vintages}), how="cross"
        )
        entity = entity.with_efficiency(
            input_commodity,
            RegionVintageArray(region=provinces, vintage=vintages).fill_from_df(
                end_use_by_vintage, value_col="efficiency"
            ),
            output_commodity=_demand_commodity(end_use),
            notes=f"From AEO CDM ktekx technology menu for technology {spec.aeo_technologies[end_use]} (AEO, {2022})",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=3, tech=2, time=2),
        ).with_limit_annual_capacity_factor(
            RegionVintageArray(region=provinces, vintage=vintages).fill_from_df(
                end_use_by_vintage, value_col="acf"
            ),
            output_commodity=_demand_commodity(end_use),
            notes=f"Mean hourly demand divided by peak hourly demand from Comstock (NREL, {2024})",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=5, tech=2, time=3),
        )
    return entity


def _warn_on_disagreeing_end_uses(
    technology: NewTechnology, served: pd.DataFrame
) -> None:
    """Warn where end uses of the same technology have different lifetimes or costs"""
    for column in ["life", "investment_cost", "fixed_cost"]:
        spread = served.groupby("region")[column].agg(["min", "max"])
        disagreeing = spread[~spread["min"].round(9).eq(spread["max"].round(9))]  # pyright: ignore[reportAttributeAccessIssue]
        if not disagreeing.empty:  # pyright: ignore[reportAttributeAccessIssue]
            logger.warning(
                f"New technology `{technology.value}`: end uses disagree on `{column}` in "
                + f"{[r.short() for r in disagreeing.index]}; using the space heating value"  # pyright: ignore[reportAttributeAccessIssue]
            )


def _demand_commodity(end_use: CommercialEndUse) -> str:
    return get_commodity_name(
        CANOESector.Commercial, end_use.get_short_name().upper(), is_demand=True
    )

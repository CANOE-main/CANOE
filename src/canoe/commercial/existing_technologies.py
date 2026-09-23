"""
Existing (installed stock) technologies serving commercial end-use demands.

Takes the per (province, end_use, fuel) parameters estimated in `build.py` and turns
them into `FuelServingTechnologyEntity` objects, one per end use. Nothing in here
touches the database; the caller decides when to `.build()` the returned entities.

Existing stock is fully defined by:

    DEM = SEC x EFF = CAP x C2A x ACF

with C2A = 1 (capacity in PJ/y, activity in PJ), so CAP = DEM / ACF.
"""

from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode
from loguru import logger

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.fuel_serving_tech import FuelServingTechnologyEntity
from canoe.common import (
    CANOEFuel,
    CANOEProvince,
    CANOESector,
    DataQualityProfile,
)
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_commodity_name,
)

if TYPE_CHECKING:
    from .end_uses import CommercialEndUse


def build_existing_technologies(
    existing_techs: pd.DataFrame,
    existing_technologies_fuels: dict["CommercialEndUse", list[CANOEFuel]],
    provinces: list[CANOEProvince],
    model_periods: list[int],
    capacity_min_tolerance: float,
    missing_data_behavior: Literal["error", "warning"],
    data_id: DatasetIdentifier,
) -> dict["CommercialEndUse", FuelServingTechnologyEntity]:
    """
    Build one existing-capacity fuel serving technology entity per end use.

    params:
    - existing_techs: one row per (province, end_use, fuel) with columns
      `province`, `end_use`, `fuel`, `dem`, `acf`, `avg_eff`, `avg_life`, `avg_fixed_cost`.
      Not modified.
    - existing_technologies_fuels: fuels we expect to have existing stock for, per end use
    - model_periods: periods fixed costs are written for (horizon end excluded)
    - capacity_min_tolerance: existing capacity is dropped for rows whose share of their
      province's total existing-stock demand is below this fraction

    End uses with no available fuels are left out of the returned dict.
    """
    existing_techs = existing_techs.assign(
        capacity=_compute_existing_capacity(existing_techs, capacity_min_tolerance)
    )
    first_period = model_periods[0]

    # end_use -> { fuel -> labeled array }
    tech_lifetimes = _compute_tech_lifetimes(provinces, existing_techs)
    tech_efficiencies, tech_capacities = _compute_tech_efficiencies_and_capacities(
        provinces,
        tech_lifetimes,
        first_period,
        first_period,
        existing_techs,
    )
    tech_fixed_costs = _compute_tech_fixed_costs(
        model_periods, first_period, provinces, existing_techs
    )

    entities: dict[CommercialEndUse, FuelServingTechnologyEntity] = {}
    for end_use, fuels in existing_technologies_fuels.items():
        available_fuels = _resolve_available_fuels(
            end_use, fuels, existing_techs, missing_data_behavior
        )
        if not available_fuels:
            continue

        eu_name = end_use.get_full_name()
        entities[end_use] = _existing_fuel_serving_technology(
            end_use,
            available_fuels,
            provinces,
            data_id,
            lifetimes=tech_lifetimes[eu_name],
            efficiencies=tech_efficiencies[eu_name],
            capacities=tech_capacities[eu_name],
            fixed_costs=tech_fixed_costs[eu_name],
        )
    return entities


def _compute_existing_capacity(
    existing_techs: pd.DataFrame,
    capacity_min_tolerance: float,
) -> pd.Series:
    """
    CAP = DEM / ACF, dropping tiny energy consumptions: rows below `capacity_min_tolerance`
    of their province's total existing-stock demand
    """
    capacity = existing_techs["dem"] / existing_techs["acf"]
    province_dem = existing_techs.groupby("province")["dem"].transform("sum")
    return capacity.where(
        existing_techs["dem"] / province_dem > capacity_min_tolerance,
        0,
    )


def _resolve_available_fuels(
    end_use: "CommercialEndUse",
    fuels: list[CANOEFuel],
    existing_techs: pd.DataFrame,
    missing_data_behavior: Literal["error", "warning"],
) -> set[CANOEFuel]:
    """
    Fuels in `fuels` for which the end use has non-zero existing capacity.
    Warns (or raises) about expected fuels without data and fuels dropped for low capacity.
    """
    # Check what fuels we have information for this end use
    eu_df = existing_techs[existing_techs["end_use"] == end_use.get_full_name()]
    original_fuels = set(eu_df.fuel.unique())
    eu_df: Any = eu_df[eu_df.capacity > 0]
    df_fuels = eu_df.fuel.unique()
    missing_fuels = set(fuels) - set(df_fuels)
    ignored_fuels = original_fuels - set(df_fuels)

    if missing_fuels:
        if missing_data_behavior == "warning":
            logger.warning(
                f"Missing data for fuels for end use {end_use.get_full_name()}: {missing_fuels}, skipping"
            )
        elif missing_data_behavior == "error":
            raise ValueError(
                f"Missing data for fuels for end use {end_use.get_full_name()}: {missing_fuels}"
            )
    available_fuels = set(df_fuels) - missing_fuels
    if len(available_fuels) == 0:
        logger.warning(
            f"No available fuels for end use {end_use.get_full_name()}, skipping"
        )
        return available_fuels
    if ignored_fuels:
        logger.warning(
            f"Ignored fuels for end use {end_use.get_full_name()} due to low capacity: {ignored_fuels}"
        )
    return available_fuels


def _existing_fuel_serving_technology(
    end_use: "CommercialEndUse",
    fuels: set[CANOEFuel],
    provinces: list[CANOEProvince],
    data_id: DatasetIdentifier,
    lifetimes: dict[CANOEFuel, RegionalValuesArray],
    efficiencies: dict[CANOEFuel, RegionVintageArray],
    capacities: dict[CANOEFuel, RegionVintageArray],
    fixed_costs: dict[CANOEFuel, RegionVintagePeriodArray],
) -> FuelServingTechnologyEntity:
    """Technologies that serve fuel (or electricity) to the end use demand"""
    efficiency_notes = (
        "Average efficiency of installed stock estimated using shares of secondary energy consumption. "
        f"Secondary energy consumption shares calculated from fuel share by end use (NRCan, {2022}) "
        f"further indexed to service demand shares divided by efficiencies for installed base technologies "
        f"of the same end use and fuel (AEO, {2022})."
    )
    capacity_notes = (
        f"Secondary energy consumption shares calculated from fuel share by end use (NRCan, {2022}) "
        f"times average efficiency for installed base technologies (AEO, {2022}) "
        f"divided by estimated annual capacity factor (NREL, {2024})"
    )
    fixed_cost_note = f"Average maintenance cost of installed stock indexed to shares of service demand by end use and fuel (AEO, {2022})"

    out_commodity_name = get_commodity_name(
        CANOESector.Commercial,
        end_use.get_short_name().upper(),
        is_demand=True,
    )
    return (
        FuelServingTechnologyEntity(
            sector=CANOESector.Commercial,
            short_desc=end_use.get_short_name().upper(),
            fuels=list(fuels),
            fuel_import_flag={
                f: CommodityTypeCode.P
                if f == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for f in fuels
            },
            output_commodity_name=out_commodity_name,
            capacity_scope=TechnologyCapacityScope.Existing,
            data_id=data_id,
        )
        .set_annual()
        .with_lifetimes(
            lifetimes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
        )
        .with_capacity_to_activity(
            {f: RegionalValuesArray(region=provinces, fill=1) for f in fuels},
            units="1",  # Equal input and output units
        )
        .with_efficiencies(
            efficiencies,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=3, tech=2, time=2),
            notes=efficiency_notes,
        )
        .with_existing_capacities(
            capacities,
            notes=capacity_notes,
            units="PJ",  # TODO: Double check
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=1),
        )
        .with_fixed_costs(
            fixed_costs,
            notes=fixed_cost_note,
            units="M$/PJ",
            data_quality=DataQualityProfile(cred=1, geog=2, struc=1, tech=2, time=2),
        )
    )


def _compute_tech_lifetimes(
    provinces: list[CANOEProvince],
    existing_techs: pd.DataFrame,
) -> dict[str, dict[CANOEFuel, RegionalValuesArray]]:
    tech_lifetimes: dict[str, dict[CANOEFuel, RegionalValuesArray]] = {}
    re_indexed_df = (
        existing_techs.set_index(["end_use", "fuel"])
        .rename(columns={"province": "region"})
        .sort_index()
        .copy()
    )

    for end_use in existing_techs["end_use"].unique():
        fuels = existing_techs[existing_techs["end_use"] == end_use].fuel.unique()
        tech_lifetimes[end_use] = {}
        for fuel in fuels:
            tech_lifetimes[end_use][fuel] = RegionalValuesArray(
                region=provinces
            ).fill_from_df(
                re_indexed_df.loc[(end_use, fuel)][["region", "avg_life"]],
                value_col="avg_life",
            )

    return tech_lifetimes


def _stock_vintages(
    lifetime: int,
    vint_interval: int,
    stock_year: int,
    first_period: int,
) -> tuple[list[int], list[float]]:

    vint_last = stock_year - stock_year % vint_interval  # first stepped back vint

    # Return any stepped back vintages that are feasible
    vints = list(range(int(vint_last), int(stock_year - lifetime), -int(vint_interval)))
    vints.sort()

    if stock_year not in vints:
        vints.append(stock_year)

    # Has to be an existing vintage but we often use e.g. 2024 to represent end of 2025
    # because Temoa traps us into start-of-period indexing
    if vints[-1] >= first_period:
        vints[-1] = first_period - 1

    # Only one vintage so all weight in there
    if len(vints) == 1:
        weights = [1.0]
    # Stock year lands on a stepped vintage so divide evenly
    elif stock_year == vint_last:
        weights = [1 / len(vints)] * len(vints)
    # Stock year is after last stepped vintage so give it a lesser weighting proportional to time interval
    else:
        weights = [vint_interval / (vints[-1] - vints[0])] * (len(vints) - 1) + [
            stock_year % vint_interval / (vints[-1] - vints[0])
        ]

    return vints, weights


def _compute_tech_efficiencies_and_capacities(
    provinces: list[CANOEProvince],
    tech_lifetimes: dict[str, dict[CANOEFuel, RegionalValuesArray]],
    stock_year: int,
    first_period: int,
    existing_techs: pd.DataFrame,
) -> tuple[
    dict[str, dict[CANOEFuel, RegionVintageArray]],
    dict[str, dict[CANOEFuel, RegionVintageArray]],
]:
    tech_efficiencies: dict[str, dict[CANOEFuel, RegionVintageArray]] = {}
    tech_capacities: dict[str, dict[CANOEFuel, RegionVintageArray]] = {}

    for end_use, fuel_lifetimes in tech_lifetimes.items():
        tech_efficiencies[end_use] = {}
        tech_capacities[end_use] = {}
        for fuel, lifetimes in fuel_lifetimes.items():
            lifetimes = lifetimes.to_records()
            tech_params = (
                existing_techs.set_index(["end_use", "fuel"])
                .sort_index()
                .loc[end_use, fuel]
                .reset_index()
                .set_index("province")
            )
            # re-group into region, vintage, weight df
            vint_rows = []
            for record in lifetimes:
                vintages, weights = _stock_vintages(
                    record["value"],
                    vint_interval=5,  # TODO: Hard-coded
                    stock_year=stock_year,
                    first_period=first_period,
                )
                for vintage, weight in zip(vintages, weights):
                    vint_rows.append((record["region"], vintage, weight))
            vint_df = pd.DataFrame(vint_rows, columns=["region", "vintage", "weight"])
            vint_df["efficiency"] = tech_params.loc[vint_df["region"]]["avg_eff"].values
            vint_df["capacity"] = (
                tech_params.loc[vint_df["region"]]["capacity"].values
                * vint_df["weight"].values
            )

            # Put back into Region, Vintage labeled array
            tech_efficiencies[end_use][fuel] = RegionVintageArray(
                region=provinces, vintage=vint_df.vintage.unique()
            ).fill_from_df(vint_df, value_col="efficiency")

            # Put back into Region, Vintage labeled array
            tech_capacities[end_use][fuel] = RegionVintageArray(
                region=provinces, vintage=vint_df.vintage.unique()
            ).fill_from_df(vint_df, value_col="capacity")

    return tech_efficiencies, tech_capacities


def _compute_tech_fixed_costs(
    periods: list[int],
    stock_year: int,
    provinces: list[CANOEProvince],
    existing_techs: pd.DataFrame,
) -> dict[str, dict[CANOEFuel, RegionVintagePeriodArray]]:
    tech_fixed_costs: dict[str, dict[CANOEFuel, RegionVintagePeriodArray]] = {}
    existing_vintages = [
        _stock_vintages(
            life,
            vint_interval=5,  # TODO: Hard-coded
            stock_year=stock_year,
            first_period=periods[0],
        )[0]
        for life in existing_techs["avg_life"]
    ]
    re_indexed_df = (
        existing_techs.assign(existing_vintages=existing_vintages)
        .set_index(["end_use", "fuel"])
        .rename(columns={"province": "region"})
        .sort_index()
    )

    for end_use in existing_techs["end_use"].unique():
        fuels = existing_techs[existing_techs["end_use"] == end_use].fuel.unique()
        tech_fixed_costs[end_use] = {}
        for fuel in fuels:
            tech_df = re_indexed_df.loc[(end_use, fuel)]
            # Union of the existing vintages across all regions
            vintages = sorted(set().union(*tech_df["existing_vintages"]))
            df = (
                tech_df[["avg_fixed_cost", "existing_vintages", "region", "avg_life"]]
                .explode("existing_vintages")
                .rename(columns={"existing_vintages": "vintage"})
                .assign(key=1)
                .merge(pd.DataFrame({"period": periods, "key": 1}), on="key")
                .drop(columns="key")
            )
            df = df[df.vintage <= df.period]
            df: Any = df[df.vintage + df.avg_life > df.period]

            labeled_array = RegionVintagePeriodArray(
                region=provinces,
                vintage=vintages,
                period=periods,
            ).fill_from_df(
                df,
                dims=["region", "vintage", "period"],
                value_col="avg_fixed_cost",
            )

            tech_fixed_costs[end_use][fuel] = labeled_array

    return tech_fixed_costs

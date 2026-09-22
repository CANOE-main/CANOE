# pyright: reportImportCycles=false

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, DataSet
from loguru import logger

from canoe.canoe_objects.demand import (
    DemandEntity,
    DemandSeriesArray,
    DemandSpecificDistributionArray,
)
from canoe.canoe_objects.fuel_serving_tech import (
    FuelServingTechnologyEntity,
    RegionalValuesArray,
)
from canoe.canoe_objects.technology import RegionVintageArray
from canoe.commercial.comstock_processing import load_and_process_comstock
from canoe.commercial.existing_capacity import (
    compute_existing_tech_life_params,
)
from canoe.commercial.loaders import get_cer_gdp
from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    DataQualityProfile,
    atomic_transaction,
)
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_commodity_name,
    hour_str,
    season_str,
)

from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOECommercialConfig, CommercialEndUse


def build_commercial(cfg: "CANOECommercialConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE commercial sector.

    Units hard-coded to PJ because that is the unit of the data.

    TODO:
        - data_ids separated by province
        - data sources (require label)
    """
    logger.info(
        f"Running COMMERCIAL (high-resolution) sector on {cfg.database_file}...\n"
    )

    #
    #
    # WE NEED TO CHECK DSD!
    #
    #
    #

    # Accumulators
    sector_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Commercial,
        code_description="HR",
        version=cfg.data_version,
    )
    fuel_imports: list[CANOEFuelImport] = []

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Write data_id label (first because it impacts everything)
        datasets = [
            DataSet(data_id=sector_data_id.get_dataset_code(province=province))
            for province in cfg.provinces + [None]
        ]
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            datasets, include_nulls=True, include_defaults=True
        )
        db_conn.executemany(sql, params)

        # Load and pre-process data sources
        # Estimated from Cosmtock
        province_dsd = load_and_process_comstock(cfg)
        # Estimated from CEUD and AEO: Several parameters (avg_life, avg_eff, dem, etc) by region, end_use, fuel
        existing_techs = compute_existing_tech_life_params(
            cfg.provinces,
            cfg.ceud_config,
            cfg.data_cache_config,
            cfg.aeo_config,
        )
        gdp_projections_index = get_cer_gdp(cfg.data_cache_config, base_year=2022)

        # Compute parameters
        # ------------------
        # - Demand series (demand projections)
        #   Adjust by gdp projections and reshape as end_use, region, period, demand
        demand_df = _compute_end_use_demand(
            existing_techs, gdp_projections_index, cfg.provinces
        )

        # - Demand specific distribution
        #   Reorganize data in long-form region, end_use, season, tod, value
        dsd_df = _compute_dsd_frame(province_dsd, cfg.end_uses)

        # - Annual Capacity Factor => mean(DSD) / max(DSD) for the region, end_use, fuel series
        existing_techs["acf"] = _compute_annual_capacity_factor(
            existing_techs, province_dsd
        )
        # Estimate existing capacity and drop tiny energy consumptions
        existing_techs["capacity"] = existing_techs["dem"] / existing_techs["acf"]
        existing_techs["capacity"] = existing_techs["capacity"].where(
            existing_techs["dem"] / existing_techs["dem"].sum()
            > cfg.capacity_min_tolerance,
            0,
        )

        # Tech Lifetimes
        # end_use -> { fuel -> RegionalValuesArray }
        tech_lifetimes: dict[str, dict[CANOEFuel, RegionalValuesArray]] = (
            _compute_tech_lifetimes(cfg.provinces, existing_techs)
        )

        # Tech Efficiencies
        tech_efficiencies, tech_capacities = _compute_tech_efficiencies_and_capacities(
            cfg.provinces,
            tech_lifetimes,
            cfg.future_periods[0],
            cfg.future_periods[0],
            existing_techs,
        )

        # Build TEMOA Objects
        # -------------------
        # Process time-slices sets (for convenience only)
        time_slices = cfg.dsd_time_slices.as_list()
        seasons = list({t.season for t in time_slices})
        tods = list({t.tod for t in time_slices})

        # Demand objects
        for end_use in cfg.end_uses:
            from .config import CommercialEndUse

            if end_use == CommercialEndUse.Other:
                continue

            # Holds all demand-related data
            demand = DemandEntity(
                name=get_commodity_name(
                    CANOESector.Commercial,
                    end_use.get_short_name().upper(),
                    is_demand=True,
                ),
                commodity_description=f"demand for commercial `{end_use.get_full_name()}` energy",
                unit="PJ",
                data_id=sector_data_id,
            )

            # Demand values
            # -------------
            demand_note = (
                f"Efficiency (AEO, {2012}) times secondary energy consumption (NRCan, {2022}) "
                f"indexed to projected provincial gdp growth by (CER, {2023})"
            )
            demand_series = DemandSeriesArray(
                region=cfg.provinces, period=cfg.future_periods, fill=0.0
            ).fill_from_df(
                demand_df.loc[end_use.get_full_name()],
                dims=["region", "period"],
                value_col="dem",
            )
            demand = demand.with_demand_series(
                demand_series,
                notes=demand_note,
                # reference_code="COM-DEMAND",
                data_quality=DataQualityProfile(
                    cred=1, geog=2, struc=2, tech=2, time=3
                ),
            )

            if cfg.include_dsd:
                # DSD
                # -------------
                dsd_series = DemandSpecificDistributionArray(
                    region=cfg.provinces,
                    period=cfg.future_periods,
                    season=seasons,
                    tod=tods,
                ).fill_from_df(
                    dsd_df[dsd_df.end_use == end_use.get_full_name()],
                    dims=["region", "season", "tod"],
                    value_col="dsd",
                )  # If we leave period out, it is broadcasted

                demand = demand.with_dsd(
                    dsd_series,
                    notes="Comstock hourly consumption for lighting and equipment summed over all building types and normalised",
                    # reference_code="COM-COMSTOCK",
                    data_quality=DataQualityProfile(
                        cred=1, geog=2, struc=1, tech=2, time=3
                    ),
                )

            # Write demand to database
            # -------------
            logger.debug(f"Writing demand entities `{end_use}` to database")
            demand.build(db_conn)

        # Existing Capacity
        for end_use, fuels in cfg.existing_technologies_fuels.items():
            # Check what fuels we have information for this end use
            eu_df = existing_techs[existing_techs["end_use"] == end_use.get_full_name()]
            original_fuels = set(eu_df.fuel.unique())
            eu_df: Any = eu_df[eu_df.capacity > 0]
            df_fuels = eu_df.fuel.unique()
            missing_fuels = set(fuels) - set(df_fuels)
            ignored_fuels = original_fuels - set(df_fuels)

            if missing_fuels:
                if cfg.missing_data_behavior == "warning":
                    logger.warning(
                        f"Missing data for fuels for end use {end_use.get_full_name()}: {missing_fuels}, skipping"
                    )
                elif cfg.missing_data_behavior == "error":
                    raise ValueError(
                        f"Missing data for fuels for end use {end_use.get_full_name()}: {missing_fuels}"
                    )
            available_fuels = set(df_fuels) - missing_fuels
            if len(available_fuels) == 0:
                logger.warning(
                    f"No available fuels for end use {end_use.get_full_name()}, skipping"
                )
                continue
            if ignored_fuels:
                logger.warning(
                    f"Ignored fuels for end use {end_use.get_full_name()} due to low capacity: {ignored_fuels}"
                )

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

            # This builds all technologies that serve fuel (or electricity) to the demand points
            out_commodity_name = get_commodity_name(
                CANOESector.Commercial,
                end_use.get_short_name().upper(),
                is_demand=True,
            )
            fuel_serving_technologies = (
                FuelServingTechnologyEntity(
                    sector=CANOESector.Commercial,
                    short_desc=end_use.get_short_name().upper(),
                    fuels=list(available_fuels),
                    fuel_import_flag={
                        f: CommodityTypeCode.P
                        if f == CANOEFuel.Electricity
                        else CommodityTypeCode.A
                        for f in available_fuels
                    },
                    output_commodity_name=out_commodity_name,
                    capacity_scope=TechnologyCapacityScope.Existing,
                    data_id=sector_data_id,
                )
                .set_annual()
                .with_lifetimes(
                    tech_lifetimes[end_use.get_full_name()],
                    data_quality=DataQualityProfile(
                        cred=1, geog=2, struc=2, tech=2, time=3
                    ),
                )
                .with_capacity_to_activity(
                    {
                        f: RegionalValuesArray(region=cfg.provinces, fill=1)
                        for f in available_fuels
                    },
                    units="1",  # Equal input and output units
                )
                .with_efficiencies(
                    tech_efficiencies[end_use.get_full_name()],
                    data_quality=DataQualityProfile(
                        cred=1, geog=2, struc=3, tech=2, time=2
                    ),
                    notes=efficiency_notes,
                )
                .with_existing_capacities(
                    tech_capacities[end_use.get_full_name()],
                    notes=capacity_notes,
                    units="PJ",  # TODO: Double check
                    data_quality=DataQualityProfile(
                        cred=1, geog=2, struc=2, tech=2, time=1
                    ),
                )
            )

            logger.debug(
                f"Writing fuel serving technology entities `{end_use}` to database"
            )
            fuel_serving_technologies.build(db_conn)

    return CANOEModuleOutput(fuel_imports=fuel_imports)


def _compute_end_use_demand(
    existing_capacity: pd.DataFrame,
    gdp_projections_index: pd.DataFrame,
    provinces: list[CANOEProvince],
) -> pd.DataFrame:
    """
    Compute end-use demand for each end-use and region over the projection period.
    Adjust by gdp projections and reshape as end_use, region, period, demand
    """
    n_end_uses = len(existing_capacity.end_use.unique())
    demand_df = (
        existing_capacity[["end_use", "province", "dem"]]
        .reset_index()
        .rename({"province": "region"}, axis=1)
        .groupby(["end_use", "region"])
        .dem.sum()
    )  # end_use, region => 2022 demand
    demand_df = pd.concat(
        [demand_df * gdp_factor for gdp_factor in gdp_projections_index.values]
    ).reset_index()
    demand_df["period"] = np.repeat(
        gdp_projections_index.index, n_end_uses * len(provinces)
    )
    return demand_df.set_index("end_use")


def _compute_annual_capacity_factor(
    existing_techs: pd.DataFrame,
    province_dsd: dict[CANOEProvince, pd.DataFrame],
) -> pd.Series:
    """ACF = mean(DSD) / max(DSD)"""

    acfs = {
        province: (dsd_df.mean(axis=0) / dsd_df.max(axis=0))
        for province, dsd_df in province_dsd.items()
    }

    return pd.Series(
        existing_techs.apply(
            lambda r: acfs[r.province][f"{r.end_use} {r.fuel.get_desc_name()}"],  # pyright: ignore[reportUnknownLambdaType]
            axis=1,
        ),
        name="acf",
    )


def _compute_dsd_frame(
    province_dsd: dict[CANOEProvince, pd.DataFrame], end_uses: list["CommercialEndUse"]
):
    frames = []
    for province, df in province_dsd.items():
        tmp = df[[eu.get_full_name() for eu in end_uses]].reset_index(names="hour")  # pyright: ignore[reportCallIssue]
        long = tmp.melt(id_vars="hour", var_name="end_use", value_name="dsd")
        long.insert(0, "region", province)
        long["tod"] = ((long["hour"] % 24) + 1).apply(hour_str)
        long["season"] = ((long["hour"] // 24) + 1).apply(season_str)
        frames.append(long)
    df_out = pd.concat(frames, ignore_index=True)

    return df_out


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


if __name__ == "__main__":
    # build_database()
    ...

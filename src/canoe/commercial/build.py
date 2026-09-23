# pyright: reportImportCycles=false

from typing import TYPE_CHECKING, Any

import pandas as pd
from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.canoe_objects.demand import (
    DemandEntity,
    DemandSeriesArray,
    DemandSpecificDistributionArray,
)
from canoe.commercial.comstock_processing import load_and_process_comstock
from canoe.commercial.existing_capacity import (
    compute_existing_tech_life_params,
    load_total_secondary_energy,
)
from canoe.commercial.existing_technologies import build_existing_technologies
from canoe.commercial.loaders import get_cer_gdp
from canoe.commercial.other_end_use import build_other_technology
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
    from .config import CommercialEndUse  # runtime import: config imports this module

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
        # - Other: secondary energy use not used for space heating and cooling (province, fuel, sec)
        other_config = cfg.end_uses.other
        other_sec: pd.DataFrame | None = None
        if other_config is not None:
            other_sec = _compute_other_secondary_energy(
                load_total_secondary_energy(
                    cfg.provinces, cfg.ceud_config, cfg.data_cache_config
                ),
                existing_techs,
                other_config.fuels,
                other_config.min_fuel_share,
            )

        # - Demand series (demand projections)
        #   Adjust by gdp projections and reshape as end_use, region, period, demand
        base_demand: Any = existing_techs[["end_use", "province", "dem"]]
        if other_sec is not None:
            # Served with efficiency 1, so demand equals secondary energy use
            other_demand = other_sec.assign(
                end_use=CommercialEndUse.Other.get_full_name(), dem=other_sec["sec"]
            )[["end_use", "province", "dem"]]
            base_demand = pd.concat([base_demand, other_demand], ignore_index=True)
        demand_df = _compute_end_use_demand(
            base_demand,
            gdp_projections_index,
            cfg.period_end_years,
        )

        # - Demand specific distribution
        #   Reorganize data in long-form region, end_use, season, tod, value
        dsd_df = _compute_dsd_frame(province_dsd, cfg.end_uses.enabled())

        # - Annual Capacity Factor => mean(DSD) / max(DSD) for the region, end_use, fuel series
        existing_techs["acf"] = _compute_annual_capacity_factor(
            existing_techs, province_dsd
        )

        # Build TEMOA Objects
        # -------------------
        # Process time-slices sets (for convenience only)
        time_slices = cfg.dsd_time_slices.as_list()
        seasons = sorted({t.season for t in time_slices})
        tods = sorted({t.tod for t in time_slices})

        # Demand objects
        demand_notes = {
            CommercialEndUse.SpaceHeating: (
                f"Efficiency (AEO, {2012}) times secondary energy consumption (NRCan, {2022}) "
                f"indexed to projected provincial gdp growth by (CER, {2023})"
            ),
            CommercialEndUse.SpaceCooling: (
                f"Efficiency (AEO, {2012}) times secondary energy consumption (NRCan, {2022}) "
                f"indexed to projected provincial gdp growth by (CER, {2023})"
            ),
            CommercialEndUse.Other: (
                "Annual secondary energy consumption summed over all fuels minus space "
                f"heating and cooling (NRCan, {2022}) indexed to projected provincial gdp "
                f"growth by (CER, {2023})"
            ),
        }
        for end_use in cfg.end_uses.enabled():
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
            demand_series = DemandSeriesArray(
                region=cfg.provinces, period=cfg.model_periods, fill=0.0
            ).fill_from_df(
                demand_df.loc[end_use.get_full_name()],
                dims=["region", "period"],
                value_col="dem",
            )
            demand = demand.with_demand_series(
                demand_series,
                notes=demand_notes[end_use],
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
                    period=cfg.model_periods,
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

        # Existing Capacity (SPH and SPC)
        existing_technologies = build_existing_technologies(
            existing_techs,
            {
                end_use: end_use_config.existing_fuels
                for end_use, end_use_config in cfg.end_uses.existing_stock().items()
            },
            cfg.provinces,
            cfg.model_periods,
            cfg.capacity_min_tolerance,
            cfg.missing_data_behavior,
            sector_data_id,
        )
        for end_use, fuel_serving_technologies in existing_technologies.items():
            logger.debug(
                f"Writing fuel serving technology entities `{end_use}` to database"
            )
            fuel_serving_technologies.build(db_conn)

            # Add fuel imports declaration
            fuel_imports += [
                CANOEFuelImport(sector=CANOESector.Commercial, fuel=f)
                for f in fuel_serving_technologies.fuels
            ]

        # Other
        if other_config is not None and other_sec is not None:
            other_technologies = build_other_technology(
                other_sec,
                other_config,
                cfg.provinces,
                cfg.model_periods,
                cfg.period_end_years,
                cfg.ceud_config.base_year,
                sector_data_id,
            )
            logger.debug("Writing fuel serving technology entities `Other` to database")
            other_technologies.build(db_conn)

            fuel_imports += [
                CANOEFuelImport(sector=CANOESector.Commercial, fuel=f)
                for f in other_technologies.fuels
            ]

    return CANOEModuleOutput(fuel_imports=fuel_imports)


def _compute_other_secondary_energy(
    total_sec: pd.DataFrame,
    existing_techs: pd.DataFrame,
    fuels: list[CANOEFuel],
    min_fuel_share: float,
) -> pd.DataFrame:
    """
    Secondary energy use of `other`: total minus space heating and cooling, by province
    and fuel. Fuels below `min_fuel_share` of a province's `other` energy use (including
    negative remainders) and fuels not in `fuels` are dropped.

    params:
    - total_sec: province, fuel, sec
    - existing_techs: province, end_use, fuel, sec

    Returns province, fuel, sec
    """
    sec = total_sec.set_index(["province", "fuel"])["sec"]
    sphc_sec = existing_techs.groupby(["province", "fuel"])["sec"].sum()
    other_sec = (sec - sphc_sec.reindex(sec.index, fill_value=0)).reset_index()  # pyright: ignore[reportAttributeAccessIssue]

    share = other_sec["sec"] / other_sec.groupby("province")["sec"].transform("sum")
    other_sec = other_sec[share > min_fuel_share]

    dropped = other_sec[~other_sec["fuel"].isin(fuels)]
    if not dropped.empty:
        logger.info(
            f"Fuels not in `other` fuels left out of its demand: {set(dropped['fuel'])}"
        )
    return other_sec[other_sec["fuel"].isin(fuels)].reset_index(drop=True)


def _compute_end_use_demand(
    base_demand: pd.DataFrame,
    gdp_projections_index: pd.DataFrame,
    period_end_years: dict[int, int],
) -> pd.DataFrame:
    """
    Compute end-use demand for each end-use and region over the model periods.

    params:
    - base_demand: base-year demand with columns `end_use`, `province`, `dem`
    - gdp_projections_index: gdp indexed to the base year, by year
    - period_end_years: model period -> year it ends. Demand for a period is scaled by
      the gdp index at the end of the period.

    Returns end_use (index), region, period, dem
    """
    demand_df = (
        base_demand.rename(columns={"province": "region"})
        .groupby(["end_use", "region"], as_index=False)
        .dem.sum()
    )  # end_use, region => base-year demand
    gdp_growth = pd.DataFrame(
        {
            "period": list(period_end_years),
            "gdp_factor": gdp_projections_index.loc[
                list(period_end_years.values()), "gdp"
            ].values,
        }
    )
    demand_df = demand_df.merge(gdp_growth, how="cross")
    demand_df["dem"] = demand_df["dem"] * demand_df["gdp_factor"]
    return demand_df.drop(columns="gdp_factor").set_index("end_use")


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


if __name__ == "__main__":
    # build_database()
    ...

# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

import pandas as pd
from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.common import (
    CANOEFuel,
    CANOEModuleOutput,
    CANOESector,
    atomic_transaction,
)
from canoe.common.naming import DatasetIdentifier
from canoe.common.projections import (
    DemandProjectionPoint,
    get_gdp_table,
    growth_by_period,
    growth_notes,
)

from .energy_use import (
    check_fuel_data,
    compute_energy_use_by_source,
    compute_total_energy_use,
    load_ceud_tables,
)
from .entities import build_agriculture_demand, build_agriculture_technology
from .input_splits import InputSplitStrategy, compute_input_splits
from .loaders import get_statcan_atlantic_agriculture_shares
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEAgricultureConfig


def build_agriculture(cfg: "CANOEAgricultureConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE agriculture sector.

    Units hard-coded to PJ because that is the unit of the data.
    """
    logger.info(
        f"Running AGRICULTURE (high-resolution) sector on {cfg.database_file}...\n"
    )

    sector_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Agriculture,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Agriculture data set: {sector_data_id.get_dataset_code()}")

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # NRCan CEUD: agriculture energy use (PJ), total and by energy source, with the
        # Atlantic table split among the Atlantic provinces by StatCan shares
        ceud = load_ceud_tables(
            cfg.provinces, cfg.ceud_data_year, cfg.data_cache_config
        )
        atlantic_shares = get_statcan_atlantic_agriculture_shares()
        total_energy_use = compute_total_energy_use(ceud, atlantic_shares)
        energy_use_by_source = compute_energy_use_by_source(ceud, atlantic_shares)
        check_fuel_data(energy_use_by_source, cfg.fuels, cfg.missing_data_behavior)
        # Projected GDP (national or by province, see `gdp`)
        gdp_table = get_gdp_table(cfg.gdp, cfg.data_cache_config)
        logger.debug(
            f"Loaded agriculture energy use of {len(total_energy_use)} provinces "
            + f"({total_energy_use['energy_use'].sum():.1f} PJ in {cfg.ceud_data_year}) "
            + f"and {len(gdp_table)} GDP projections"
        )

        # Compute parameters
        # ------------------
        # - Demand (region, period, demand): data-year energy use indexed to the
        #   projected gdp growth of the province in each period
        gdp_growth = growth_by_period(
            gdp_table,
            cfg.provinces,
            cfg.ceud_data_year,
            cfg.future_periods,
            cfg.period_step,
            cfg.demand_projection_point,
        )
        demand_df = _compute_demand(total_energy_use, gdp_growth)
        # - Input splits (region, period, fuel, split): the data-year fuel mix
        input_split_df = compute_input_splits(
            energy_use_by_source,
            cfg.fuels,
            cfg.input_split_strategy,
            cfg.remainder_fuel,
            cfg.future_periods,
        )

        # Build TEMOA Objects
        # -------------------
        # Write data_id labels (first because they impact everything)
        datasets = [
            DataSet(data_id=sector_data_id.get_dataset_code(province=province))
            for province in cfg.provinces + [None]
        ]
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            datasets, include_nulls=True, include_defaults=True
        )
        db_conn.executemany(sql, params)

        # Demand first: the technology outputs its commodity
        logger.info("Building the agriculture demand")
        build_agriculture_demand(
            demand_df,
            cfg.provinces,
            cfg.future_periods,
            notes=_demand_notes(
                cfg.ceud_data_year,
                growth_notes(gdp_growth),
                cfg.demand_projection_point,
            ),
            data_id=sector_data_id,
        ).build(db_conn)

        logger.info("Building the agriculture technology")
        technology = build_agriculture_technology(
            input_split_df,
            cfg.fuels,
            cfg.provinces,
            cfg.future_periods,
            cfg.input_split_operator,
            split_notes=_input_split_notes(
                cfg.ceud_data_year, cfg.input_split_strategy, cfg.remainder_fuel
            ),
            data_id=sector_data_id,
        )
        unused_fuels = set(cfg.fuels) - set(technology.fuels)
        if unused_fuels:
            logger.info(f"Fuels with no agriculture use, left out: {unused_fuels}")
        technology.build(db_conn)

    return CANOEModuleOutput(
        # The fuels the technology takes, where it takes them
        fuel_imports=declare_fuel_imports(
            CANOESector.Agriculture, technology.to_technology_entities()
        )
    )


def _demand_notes(
    ceud_data_year: int,
    gdp_source: str,
    demand_projection_point: DemandProjectionPoint,
) -> str:
    point = {
        DemandProjectionPoint.PeriodEnd: "at the end of each period",
        DemandProjectionPoint.PeriodStart: "at the start of each period",
        DemandProjectionPoint.Legacy: "at the start of each period, relative to the first",
    }[demand_projection_point]
    return (
        f"Total agriculture energy use (NRCan, {ceud_data_year}) indexed to projected "
        + f"gdp growth {point} ({gdp_source}). Atlantic provinces split by their "
        + f"share of agriculture energy use (StatCan, {2023})"
    )


def _input_split_notes(
    ceud_data_year: int,
    strategy: InputSplitStrategy,
    remainder_fuel: CANOEFuel,
) -> str:
    return {
        InputSplitStrategy.NRCanPercentWithRemainder: (
            f"Shares of agriculture energy use by source (NRCan, {ceud_data_year}); "
            + f"share of the sources not modelled assigned to {remainder_fuel.get_desc_name()}"
        ),
        InputSplitStrategy.EnergyWithRemainder: (
            "Agriculture energy use by source over total energy use (NRCan, "
            + f"{ceud_data_year}); energy use of the sources not modelled assigned to "
            + f"{remainder_fuel.get_desc_name()}"
        ),
        InputSplitStrategy.EnergyNormalized: (
            "Agriculture energy use by source over the energy use of the modelled "
            + f"fuels (NRCan, {ceud_data_year})"
        ),
    }[strategy]


def _compute_demand(
    total_energy_use: pd.DataFrame, gdp_growth: pd.DataFrame
) -> pd.DataFrame:
    """
    Agriculture energy demand of each province over the model periods.

    params:
    - total_energy_use: data-year energy use, columns `province`, `energy_use` (PJ)
    - gdp_growth: columns `region`, `period`, `growth` from the data year, see
      `canoe.common.projections.growth_by_period`

    Returns region, period, demand (PJ)
    """
    demand_df = total_energy_use.rename(columns={"province": "region"}).merge(
        gdp_growth[["region", "period", "growth"]], on="region"
    )
    demand_df["demand"] = demand_df["energy_use"] * demand_df["growth"]
    return demand_df[["region", "period", "demand"]]  # pyright: ignore[reportReturnType]

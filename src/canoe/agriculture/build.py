# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

import pandas as pd
from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOESector,
    atomic_transaction,
)
from canoe.common.gdp import CERScenario, GDPProjectionPoint, gdp_growth_by_period
from canoe.common.loaders import get_cer_gdp
from canoe.common.naming import DatasetIdentifier

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
        # CER: GDP indexed to the year of the CEUD energy use it scales
        gdp_projections_index = get_cer_gdp(
            cfg.data_cache_config,
            gdp_index_year=cfg.ceud_data_year,
            scenario=cfg.gdp_scenario,
        )
        logger.debug(
            f"Loaded agriculture energy use of {len(total_energy_use)} provinces "
            + f"({total_energy_use['energy_use'].sum():.1f} PJ in {cfg.ceud_data_year}) "
            + f"and GDP projections for {len(gdp_projections_index)} years"
        )

        # Compute parameters
        # ------------------
        # - Demand (region, period, demand): data-year energy use indexed to the
        #   projected gdp growth of each period
        demand_df = _compute_demand(
            total_energy_use,
            gdp_growth_by_period(
                gdp_projections_index, cfg.future_periods, cfg.gdp_projection_point
            ),
        )
        # - Input splits (region, period, fuel, split): the data-year fuel mix
        input_split_df = compute_input_splits(
            energy_use_by_source,
            cfg.fuels,
            cfg.input_split_strategy,
            cfg.remainder_fuel,
            cfg.model_periods,
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
            cfg.model_periods,
            notes=_demand_notes(
                cfg.ceud_data_year, cfg.gdp_scenario, cfg.gdp_projection_point
            ),
            data_id=sector_data_id,
        ).build(db_conn)

        logger.info("Building the agriculture technology")
        technology = build_agriculture_technology(
            input_split_df,
            cfg.fuels,
            cfg.provinces,
            cfg.model_periods,
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
        fuel_imports=[
            CANOEFuelImport(sector=CANOESector.Agriculture, fuel=fuel)
            for fuel in technology.fuels
        ]
    )


def _demand_notes(
    ceud_data_year: int,
    gdp_scenario: CERScenario,
    gdp_projection_point: GDPProjectionPoint,
) -> str:
    point = {
        GDPProjectionPoint.PeriodEnd: "at the end of each period",
        GDPProjectionPoint.PeriodStart: "at the start of each period",
        GDPProjectionPoint.Legacy: "at the start of each period, relative to the first",
    }[gdp_projection_point]
    return (
        f"Total agriculture energy use (NRCan, {ceud_data_year}) indexed to projected "
        + f"gdp growth {point} ({gdp_scenario.value}, CER, {2023}). Atlantic provinces "
        + f"split by their share of agriculture energy use (StatCan, {2023})"
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
    total_energy_use: pd.DataFrame, gdp_growth: dict[int, float]
) -> pd.DataFrame:
    """
    Agriculture energy demand of each province over the model periods.

    params:
    - total_energy_use: data-year energy use, columns `province`, `energy_use` (PJ)
    - gdp_growth: model period -> gdp growth factor from the data year, see
      `canoe.common.gdp.gdp_growth_by_period`

    Returns region, period, demand (PJ)
    """
    gdp_growth_df = pd.DataFrame(
        {"period": list(gdp_growth), "gdp_factor": list(gdp_growth.values())}
    )
    demand_df = total_energy_use.rename(columns={"province": "region"}).merge(
        gdp_growth_df, how="cross"
    )
    demand_df["demand"] = demand_df["energy_use"] * demand_df["gdp_factor"]
    return demand_df[["region", "period", "demand"]]  # pyright: ignore[reportReturnType]

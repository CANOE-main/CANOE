# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier
from canoe.common.periods import (
    ProjectionPoint,
    horizon_length,
    projection_year_by_period,
)
from canoe.common.projections import CERScenario

from .energy_mix import (
    SmallShareStrategy,
    compute_demand_and_splits,
    energy_use_by_period,
    round_energy_use,
)
from .entities import build_cef_demand, build_cef_technology
from .loaders import get_cef_end_use_demand
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOECEFConfig


def build_cef(cfg: "CANOECEFConfig") -> CANOEModuleOutput:
    """
    Main function of a CEF sector: a low-resolution sector built from the CER Canada's
    Energy Future end-use demand projections.

    Units hard-coded to PJ because that is the unit of the data.
    """
    logger.info(
        f"Running CEF {cfg.sector} ({cfg.scenario.value}) on {cfg.database_file}...\n"
    )
    if cfg.sector == CANOESector.Industry:
        logger.warning(
            "CEF industry includes agriculture: running the agriculture module as "
            + "well counts agriculture energy use twice"
        )

    sector_data_id = DatasetIdentifier(
        sector=cfg.sector,
        code_description=cfg.scenario.get_dataset_code_description(),
        version=cfg.data_version,
    )
    logger.debug(f"CEF {cfg.sector} data set: {sector_data_id.get_dataset_code()}")

    with atomic_transaction(cfg.database_file) as db_conn:
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # CER Canada's Energy Future: end-use energy demand (PJ) by province, year and
        # fuel, rounded to 0.01 PJ like the previous module
        energy = get_cef_end_use_demand(
            cfg.data_cache_config, cfg.scenario.value, cfg.sector
        )
        energy = energy.loc[energy["region"].isin(cfg.provinces)]
        energy = round_energy_use(energy)

        # Compute parameters
        # ------------------
        # - Energy demand (region, period, fuel): CEF year read by each period
        projection_years = projection_year_by_period(
            cfg.future_periods,
            cfg.period_step,
            ProjectionPoint(cfg.demand_projection_point.value),
        )
        energy_by_period = energy_use_by_period(energy, projection_years)
        # - Demand (region, period) and input splits (region, period, fuel)
        demand_df, split_df = compute_demand_and_splits(
            energy_by_period, cfg.small_share_threshold, cfg.small_share_strategy
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
        logger.info(f"Building the CEF {cfg.sector} demand")
        build_cef_demand(
            cfg.sector,
            demand_df,
            cfg.provinces,
            cfg.future_periods,
            notes=_demand_notes(cfg.scenario, cfg.sector, projection_years),
            data_id=sector_data_id,
        ).build(db_conn)

        logger.info(f"Building the CEF {cfg.sector} technology")
        technology = build_cef_technology(
            cfg.sector,
            split_df,
            cfg.provinces,
            cfg.future_periods,
            lifetime=horizon_length(cfg.future_periods, cfg.period_step),
            input_split_operator=cfg.input_split_operator,
            split_notes=_split_notes(
                cfg.scenario, cfg.small_share_threshold, cfg.small_share_strategy
            ),
            data_id=sector_data_id,
        )
        technology.build(db_conn)

    return CANOEModuleOutput(
        # The fuels the technology takes, where it takes them
        fuel_imports=declare_fuel_imports(
            cfg.sector, technology.to_technology_entities()
        )
    )


def _source(scenario: CERScenario) -> str:
    return f"CER Canada's Energy Future 2023, end-use demand ({scenario.value})"


def _demand_notes(
    scenario: CERScenario, sector: CANOESector, projection_years: dict[int, int]
) -> str:
    years = sorted(set(projection_years.values()))
    return (
        f"{sector.get_cef_sector()} end-use energy demand of the fuels modelled, in "
        + f"{years[0]}-{years[-1]} for the periods {min(projection_years)}-"
        + f"{max(projection_years)} ({_source(scenario)})"
    )


def _split_notes(
    scenario: CERScenario, threshold: float, strategy: SmallShareStrategy
) -> str:
    small = {
        SmallShareStrategy.ZeroSmallShares: "set to zero and supplied by the others",
        SmallShareStrategy.DropSmallFuels: (
            "set to zero; fuels below it in every period left out of the demand"
        ),
    }[strategy]
    return (
        f"Share of each fuel in the end-use energy demand ({_source(scenario)}). "
        + f"Shares below {threshold:g} {small}"
    )

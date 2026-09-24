# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.loaders import get_cer_gdp
from canoe.common.naming import DatasetIdentifier

from .energy_use import (
    check_fuel_data,
    compute_energy_use_by_source,
    compute_total_energy_use,
    load_ceud_tables,
)
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

        # TODO Compute parameters
        # TODO Build TEMOA Objects

    return CANOEModuleOutput(fuel_imports=[])

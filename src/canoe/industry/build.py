# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.loaders import get_cer_gdp
from canoe.common.naming import DatasetIdentifier

from .energy_use import (
    check_atlantic_shares,
    check_energy_use,
    compute_energy_use,
    compute_energy_use_by_source,
    load_ceud_tables,
)
from .loaders import get_statcan_atlantic_industry_shares
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEIndustryConfig


def build_industry(cfg: "CANOEIndustryConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE industry sector.

    Units hard-coded to PJ because that is the unit of the data.
    """
    logger.info(
        f"Running INDUSTRY (high-resolution) sector on {cfg.database_file}...\n"
    )

    sector_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Industry,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Industry data set: {sector_data_id.get_dataset_code()}")
    subsectors = cfg.modelled_subsectors()
    own_fuels = {s: cfg.fuels_of(s) for s in subsectors if cfg.fuels_of(s) != cfg.fuels}
    logger.debug(
        f"Industry subsectors: {', '.join(s.short_desc() for s in subsectors)}; "
        + f"fuels: {', '.join(f.value for f in cfg.fuels)}"
        + "".join(
            f"; {s.short_desc()} fuels: {', '.join(f.value for f in fuels)}"
            for s, fuels in own_fuels.items()
        )
        + f"; other fuels: {cfg.other_fuels}"
    )

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # NRCan CEUD: energy use (PJ) of each subsector, total and by energy source,
        # with the Atlantic tables split among the Atlantic provinces by StatCan
        # shares
        ceud = load_ceud_tables(
            cfg.provinces, subsectors, cfg.ceud_data_year, cfg.data_cache_config
        )
        atlantic_shares = get_statcan_atlantic_industry_shares()
        check_atlantic_shares(ceud, atlantic_shares, cfg.missing_data_behavior)
        energy_use = compute_energy_use(ceud, atlantic_shares)
        energy_use_by_source = compute_energy_use_by_source(ceud, atlantic_shares)
        check_energy_use(energy_use, cfg.missing_data_behavior)
        # CER: GDP indexed to the year of the CEUD energy use it scales
        gdp_projections_index = get_cer_gdp(
            cfg.data_cache_config,
            gdp_index_year=cfg.ceud_data_year,
            scenario=cfg.gdp_scenario,
        )
        logger.debug(
            f"Loaded industry energy use of {len(subsectors)} subsectors in "
            + f"{len(cfg.provinces)} provinces ({energy_use['energy_use'].sum():.1f} "
            + f"PJ in {cfg.ceud_data_year}, {len(energy_use_by_source)} rows by "
            + f"source) and GDP projections for {len(gdp_projections_index)} years"
        )

        # Compute parameters
        # ------------------
        # TODO: demand and input splits of each subsector ("Other" deducted from the
        # demand or kept as a split, per cfg.other_fuels)

        # Build TEMOA Objects
        # -------------------
        # TODO: a demand and a technology per subsector, and the free supply of
        # I_oth if cfg.other_fuels is "free"

    return CANOEModuleOutput(fuel_imports=[])

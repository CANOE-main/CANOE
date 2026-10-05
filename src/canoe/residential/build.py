# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier

from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEResidentialConfig


def build_residential(cfg: "CANOEResidentialConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE residential sector.

    Units: PJ for energy services, Glmy for lighting and Munity for appliances, the
    units of the data.
    """
    logger.info(
        f"Running RESIDENTIAL (high-resolution) sector on {cfg.database_file}...\n"
    )

    sector_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Residential,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Residential data set: {sector_data_id.get_dataset_code()}")
    new_technologies = cfg.end_uses.new_technologies()
    logger.debug(
        "Residential end uses: "
        + ", ".join(e.value for e in cfg.end_uses.enabled())
        + f"; {len(new_technologies)} new technologies: "
        + ", ".join(t.value for t in new_technologies)
        + f"; demands driven by {cfg.demand_driver.value}"
    )

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # TODO: NRCan CEUD residential tables and handbook, AEO technology menu,
        # StatCan population and lighting, CER GDP, ResStock, weather maps

        # Compute parameters
        # ------------------
        # TODO: demands, existing stock, new technologies, lighting, DSDs

        # Build TEMOA Objects
        # -------------------
        # TODO: demands, existing technologies, new technologies, lighting

    return CANOEModuleOutput(fuel_imports=[])

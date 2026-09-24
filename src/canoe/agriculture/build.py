# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier

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

        # TODO Load and pre-process data sources
        # TODO Compute parameters
        # TODO Build TEMOA Objects

    return CANOEModuleOutput(fuel_imports=[])

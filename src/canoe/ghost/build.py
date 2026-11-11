# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from canoe_schema.v4_0 import CommodityTypeCode, DataSet
from loguru import logger

from canoe.canoe_objects.commodity import FuelCommodityEntity
from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    atomic_transaction,
)
from canoe.common.naming import DatasetIdentifier
from canoe.common.validation import check_missing_regions

if TYPE_CHECKING:
    from .config import CANOEGhostConfig


def build_ghost(cfg: "CANOEGhostConfig") -> CANOEModuleOutput:
    """
    Main function of a CANOE ghost sector: registers the fuel commodities of the
    ghost's sector (e.g. `T_elc`) and declares them as fuel imports in its provinces,
    for the electricity and fuel modules to supply.
    """
    logger.info(
        f"Running GHOST {cfg.sector} on {cfg.database_file}: "
        + ", ".join(f.value for f in cfg.fuels)
        + f" in {len(cfg.provinces)} provinces\n"
    )
    data_id = DatasetIdentifier(
        sector=cfg.sector,
        code_description=cfg.dataset_code_description,
        version=cfg.data_version,
    )
    provinces = tuple(p for p in CANOEProvince if p in cfg.provinces)

    with atomic_transaction(cfg.database_file) as db_conn:
        check_missing_regions(db_conn, cfg.provinces, cfg.validation_behavior)

        # Data set of the commodity rows (sector-wide, no region)
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            [DataSet(data_id=data_id.get_dataset_code())],
            include_nulls=True,
            include_defaults=True,
        )
        db_conn.executemany(sql, params)

        for fuel in cfg.fuels:
            # Electricity is balanced per time slice, the other fuels over the year
            FuelCommodityEntity(
                sector=cfg.sector,
                fuel=fuel,
                flag=CommodityTypeCode.P
                if fuel == CANOEFuel.Electricity
                else CommodityTypeCode.A,
                data_id=data_id,
            ).build(db_conn)

    return CANOEModuleOutput(
        fuel_imports=[
            CANOEFuelImport(sector=cfg.sector, fuel=fuel, provinces=provinces)
            for fuel in cfg.fuels
        ]
    )

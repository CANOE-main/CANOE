# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.naming import DatasetIdentifier

from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEElectricityConfig


def build_electricity(
    cfg: "CANOEElectricityConfig", fuel_imports: list[CANOEFuelImport]
) -> CANOEModuleOutput:
    """
    Main function of the CANOE electricity module.

    params:
    - fuel_imports: the fuel imports declared by all the sectors that ran; this
      module supplies their electricity

    Returns the fuel imports of the generators, for the fuel module.

    Units: PJ for energy, GW for capacity, M$ of `model_currency_year`.
    """
    logger.info(f"Running ELECTRICITY supply on {cfg.database_file}...\n")

    electricity_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Electricity,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Electricity data set: {electricity_data_id.get_dataset_code()}")

    imports = electricity_imports(fuel_imports)
    logger.debug(
        f"Supplying electricity to {len(imports)} sectors: "
        + ", ".join(f"{i.sector} ({len(i.provinces)})" for i in imports)
    )
    _log_components(cfg)

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # TODO: CODERS (fleet, generic, losses, reserve, interties, demand), NREL
        # ATB, new VRE bins, IESO, StatCan, renewables.ninja, EIA T&D, ramp rates

        # Compute parameters
        # ------------------
        # TODO: grid, generation, capacity factors, storage, CCS, reliability, trade

        # Build TEMOA Objects
        # -------------------
        # TODO: grid and delivery, generators, storage, CCS retrofits, interties

    return CANOEModuleOutput(fuel_imports=[])


def electricity_imports(fuel_imports: list[CANOEFuelImport]) -> list[CANOEFuelImport]:
    """
    Electricity imports this module supplies: one per sector, in the order declared,
    in the provinces of all its declarations. Other fuels are left to the fuel
    module.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> imports = [
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.Electricity, (QC,)),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas, (ON,)),
    ...     CANOEFuelImport(CANOESector.Industry, CANOEFuel.Electricity, (ON,)),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.Electricity, (ON, QC)),
    ... ]
    >>> for i in electricity_imports(imports):
    ...     print(i.sector, [p.short() for p in i.provinces])
    Commercial ['ON', 'QC']
    Industry ['ON']
    """
    provinces: dict[CANOESector, set[CANOEProvince]] = {}
    for fuel_import in fuel_imports:
        if fuel_import.fuel != CANOEFuel.Electricity:
            continue
        provinces.setdefault(fuel_import.sector, set()).update(fuel_import.provinces)
    return [
        CANOEFuelImport(
            sector=sector,
            fuel=CANOEFuel.Electricity,
            provinces=tuple(p for p in CANOEProvince if p in regions),
        )
        for sector, regions in provinces.items()
    ]


def _log_components(cfg: "CANOEElectricityConfig"):
    generation, storage, trade = cfg.generation, cfg.storage, cfg.trade
    components = {
        "exogenous demand": cfg.exogenous_demand,
        "existing generation": not generation.skip_existing,
        "existing storage": not storage.skip_existing,
        "endogenous trade": not trade.skip_endogenous,
        "boundary trade": not trade.skip_boundary,
        "reliability": not cfg.reliability.skip,
    }
    logger.debug(
        "Electricity components: "
        + ", ".join(name for name, on in components.items() if on)
        + "; left out: "
        + (", ".join(name for name, on in components.items() if not on) or "none")
    )
    logger.debug(
        "New generation: "
        + (", ".join(t.value for t in generation.new_technologies) or "none")
        + "; CCS retrofits: "
        + (", ".join(t.value for t in generation.ccs_retrofits) or "none")
        + "; new storage: "
        + (", ".join(t.value for t in storage.new_technologies) or "none")
    )

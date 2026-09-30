# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOESector,
    atomic_transaction,
)
from canoe.common.loaders import get_exchange_and_inflation_tables
from canoe.common.naming import DatasetIdentifier

from .emission_factors import add_combustion_factor_proxies
from .loaders import (
    get_atb_fuel_prices,
    get_combustion_emission_factors,
    get_eia_energy_prices,
    get_fixed_fuel_prices,
    get_upstream_emission_factors,
)
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEFuelConfig

FUELS_SUPPLIED_ELSEWHERE: tuple[CANOEFuel, ...] = (CANOEFuel.Electricity,)
"""Fuels the sectors import that this module does not supply. Electricity will be
supplied by the electricity module."""


def build_fuel(
    cfg: "CANOEFuelConfig", fuel_imports: list[CANOEFuelImport]
) -> CANOEModuleOutput:
    """
    Main function of the CANOE fuel supply.

    params:
    - fuel_imports: the fuel imports declared by all the sectors that ran

    Returns the emission declarations of the gases written: upstream emissions under
    the fuel sector, combustion emissions under each consuming sector. The fuel
    module imports nothing itself.

    Units hard-coded to PJ and M$/PJ, the units of the model.
    """
    logger.info(f"Running FUEL supply on {cfg.database_file}...\n")

    fuel_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Fuel,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Fuel data set: {fuel_data_id.get_dataset_code()}")

    imports = imports_to_supply(fuel_imports)
    skipped: list[CANOEFuelImport] = []
    for fuel_import in fuel_imports:
        if fuel_import.fuel in FUELS_SUPPLIED_ELSEWHERE and fuel_import not in skipped:
            skipped.append(fuel_import)
    if skipped:
        logger.info(
            "Fuel imports supplied by other modules, skipped: "
            + ", ".join(f"{i.sector}:{i.fuel.value}" for i in skipped)
        )
    logger.debug(
        f"Supplying {len(imports)} fuel imports: "
        + ", ".join(f"{i.sector}:{i.fuel.value}" for i in imports)
    )

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # Prices, each in its own currency, year and units: EIA AEO Table 3
        # delivered prices by sector and fuel (2024 USD/MMBtu), NREL ATB biomass and
        # uranium (2022 USD/MMBtu), fixed report prices (2020 CAD/GJ)
        eia_prices = get_eia_energy_prices(cfg.data_cache_config)
        atb_prices = get_atb_fuel_prices(cfg.data_cache_config)
        fixed_prices = get_fixed_fuel_prices()
        # Exchange rates and inflation, to convert them to CAD of model_currency_year
        exchange, inflation = get_exchange_and_inflation_tables()
        # Emission factors (kt/PJ): combustion by sector and fuel, upstream by fuel
        combustion_factors = get_combustion_emission_factors()
        # Agriculture gasoline takes the transportation factors (none in the source)
        combustion_factors = add_combustion_factor_proxies(
            combustion_factors, cfg.reproduce_previous_emission_errors
        )
        upstream_factors = get_upstream_emission_factors()
        logger.debug(
            f"Loaded {len(eia_prices.prices)} EIA prices "
            + f"({eia_prices.prices['year'].min()}-{eia_prices.prices['year'].max()}), "
            + f"{len(atb_prices.prices)} ATB and {len(fixed_prices.prices)} fixed "
            + f"prices, exchange and inflation for {len(exchange)} and "
            + f"{len(inflation)} years, {len(combustion_factors)} combustion and "
            + f"{len(upstream_factors)} upstream emission factors"
        )

        # Compute parameters
        # ------------------
        # TODO:
        # - Delivered price (sector, fuel, period) in M$/PJ of model_currency_year,
        #   read at price_projection_point, from get_delivered_price_sources
        # - Import and distribution costs (region, period, tech): the lowest
        #   delivered price of each fuel, and the rest of each sector's price
        # - Emission activities (tech, emission): upstream on the imports, combustion
        #   on the distribution

        # Build TEMOA Objects
        # -------------------
        # TODO: data set labels, F_ethos and F_<fuel> commodities, F_IMP_<FUEL> and
        # F_<S>_<FUEL> technologies

    return CANOEModuleOutput(fuel_imports=[], emissions=[])


def imports_to_supply(fuel_imports: list[CANOEFuelImport]) -> list[CANOEFuelImport]:
    """
    Fuel imports this module supplies: each (sector, fuel) once, in the order declared,
    without the fuels supplied by other modules (`FUELS_SUPPLIED_ELSEWHERE`).

    Examples
    --------
    >>> imports = [
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.Electricity),
    ...     CANOEFuelImport(CANOESector.Agriculture, CANOEFuel.NaturalGas),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas),
    ... ]
    >>> [(str(i.sector), i.fuel.value) for i in imports_to_supply(imports)]
    [('Commercial', 'NG'), ('Agriculture', 'NG')]
    """
    supplied: list[CANOEFuelImport] = []
    for fuel_import in fuel_imports:
        if fuel_import.fuel in FUELS_SUPPLIED_ELSEWHERE or fuel_import in supplied:
            continue
        supplied.append(fuel_import)
    return supplied

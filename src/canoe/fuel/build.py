# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.loaders import get_exchange_and_inflation_tables
from canoe.common.naming import DatasetIdentifier
from canoe.common.periods import ProjectionPoint, projection_year_by_period

from .emission_factors import add_combustion_factor_proxies, check_combustion_factors
from .entities import build_fuel_supply
from .loaders import (
    get_atb_fuel_prices,
    get_combustion_emission_factors,
    get_eia_energy_prices,
    get_fixed_fuel_prices,
    get_upstream_emission_factors,
)
from .prices import (
    check_price_sources,
    compute_delivered_prices,
    convert_to_model_units,
    get_delivered_price_sources,
    split_import_and_distribution,
)
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEFuelConfig

FUELS_SUPPLIED_ELSEWHERE: tuple[CANOEFuel, ...] = (CANOEFuel.Electricity,)
"""Fuels the sectors import that this module does not supply. Electricity is
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
    skipped = list(
        dict.fromkeys(
            (i.sector, i.fuel)
            for i in fuel_imports
            if i.fuel in FUELS_SUPPLIED_ELSEWHERE
        )
    )
    if skipped:
        logger.info(
            "Fuel imports supplied by other modules, skipped: "
            + ", ".join(f"{sector}:{fuel.value}" for sector, fuel in skipped)
        )
    logger.debug(
        f"Supplying {len(imports)} fuel imports: "
        + ", ".join(f"{i.sector}:{i.fuel.value} ({len(i.provinces)})" for i in imports)
    )

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, imports, db_conn)

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
        # (sector, fuel) supplied: those with a price (the others are reported with
        # missing_data_behavior and not supplied), and their emission factors
        sources = get_delivered_price_sources(cfg.reproduce_previous_price_errors)
        supplied = check_price_sources(imports, sources, cfg.missing_data_behavior)
        check_combustion_factors(
            [(i.sector, i.fuel) for i in supplied],
            combustion_factors,
            cfg.missing_data_behavior,
        )
        # - Delivered price (sector, fuel, period) in M$/PJ of model_currency_year,
        #   of every sector of the price table for the fuels supplied, read at
        #   price_projection_point
        projection_years = projection_year_by_period(
            cfg.future_periods, cfg.period_step, cfg.price_projection_point
        )
        delivered_prices = compute_delivered_prices(
            sources,
            list(dict.fromkeys(i.fuel for i in supplied)),
            projection_years,
            *(
                convert_to_model_units(
                    source,
                    cfg.model_currency_year,
                    exchange,
                    inflation,
                    cfg.reproduce_previous_price_errors,
                )
                for source in (eia_prices, atb_prices, fixed_prices)
            ),
        )
        # - Import costs (region, period, fuel): the lowest delivered price of each
        #   fuel; distribution costs (region, period, sector, fuel): the rest of each
        #   sector's price
        import_costs, distribution_costs = split_import_and_distribution(
            delivered_prices, supplied, cost_notes_suffix=_cost_notes_suffix(cfg)
        )

        # Build TEMOA Objects
        # -------------------
        # Write data_id labels (first because they impact everything)
        datasets = [
            DataSet(data_id=fuel_data_id.get_dataset_code(province=province))
            for province in cfg.provinces + [None]
        ]
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            datasets, include_nulls=True, include_defaults=True
        )
        db_conn.executemany(sql, params)

        # F_ethos and the F_<fuel> commodities, then the imports and distribution
        # technologies (the sectors already built their fuel commodities)
        supply = build_fuel_supply(
            import_costs,
            distribution_costs,
            upstream_factors,
            combustion_factors,
            lifetime=cfg.period_step,
            data_id=fuel_data_id,
        )
        logger.info(
            f"Building {len(supply.imports)} fuel imports and "
            + f"{len(supply.distributions)} distribution technologies"
        )
        supply.build(db_conn)

    return CANOEModuleOutput(fuel_imports=[], emissions=supply.emissions)


def _cost_notes_suffix(cfg: "CANOEFuelConfig") -> str:
    point = {
        ProjectionPoint.PeriodEnd: "the end of each period",
        ProjectionPoint.PeriodStart: "the label year of each period",
    }[cfg.price_projection_point]
    conversion = (
        "; converted as the previous fuel module (see FUEL_MODULE_BUGS.md)"
        if cfg.reproduce_previous_price_errors
        else ""
    )
    return (
        f". Projected prices read at {point}, in M$/PJ of "
        + f"{cfg.model_currency_year} CAD{conversion}"
    )


def imports_to_supply(fuel_imports: list[CANOEFuelImport]) -> list[CANOEFuelImport]:
    """
    Fuel imports this module supplies: one per (sector, fuel), in the order declared,
    in the provinces of all its declarations, without the fuels supplied by other
    modules (`FUELS_SUPPLIED_ELSEWHERE`).

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> imports = [
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas, (QC,)),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.Electricity, (ON,)),
    ...     CANOEFuelImport(CANOESector.Agriculture, CANOEFuel.NaturalGas, (ON,)),
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas, (ON, QC)),
    ... ]
    >>> for i in imports_to_supply(imports):
    ...     print(i.sector, i.fuel, [p.short() for p in i.provinces])
    Commercial NaturalGas ['ON', 'QC']
    Agriculture NaturalGas ['ON']
    """
    provinces: dict[tuple[CANOESector, CANOEFuel], set[CANOEProvince]] = {}
    for fuel_import in fuel_imports:
        if fuel_import.fuel in FUELS_SUPPLIED_ELSEWHERE:
            continue
        provinces.setdefault((fuel_import.sector, fuel_import.fuel), set()).update(
            fuel_import.provinces
        )
    return [
        CANOEFuelImport(
            sector=sector,
            fuel=fuel,
            provinces=tuple(p for p in CANOEProvince if p in regions),
        )
        for (sector, fuel), regions in provinces.items()
    ]

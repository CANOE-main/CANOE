# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.currency import currency_conversion_factor
from canoe.common.loaders import get_exchange_and_inflation_tables
from canoe.common.naming import DatasetIdentifier
from canoe.common.periods import (
    ProjectionPoint,
    horizon_length,
    projection_year_by_period,
)
from canoe.common.validation import check_missing_existing_periods

from .catalogue import GenerationTechnology
from .fleet import existing_generators
from .generation.entities import (
    ExistingGeneration,
    ExistingGenerationNotes,
    build_existing_generation,
)
from .generation.parameters import (
    cogeneration_activity,
    existing_efficiencies,
    existing_lifetimes,
    existing_om_costs,
)
from .loaders import (
    get_aeo_transmission_distribution_costs,
    get_atb_generation,
    get_coders_generation_generic,
    get_coders_generators,
    get_coders_system_line_losses,
)
from .supply.entities import build_grid
from .supply.parameters import grid_variable_costs, transmission_efficiencies
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
        validate_db_against_config(cfg, imports, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # Grid: CODERS system line losses (fraction), EIA AEO transmission and
        # distribution costs (2024 USD c/kWh)
        line_losses = get_coders_system_line_losses()
        grid_costs = get_aeo_transmission_distribution_costs()
        # Exchange rates and inflation, to convert costs to CAD of model_currency_year
        exchange, inflation = get_exchange_and_inflation_tables()
        logger.debug(
            f"Loaded line losses of {len(line_losses)} provinces, "
            + f"{len(grid_costs.costs)} grid costs "
            + f"({grid_costs.costs['year'].min()}-{grid_costs.costs['year'].max()})"
        )
        # Generation: CODERS generators (MW, GWh) and generic parameters (CAD),
        # NREL ATB heat rates and O&M costs of the ATB technologies (USD)
        units = get_coders_generators(cfg.data_cache_config)
        generic = get_coders_generation_generic(cfg.data_cache_config)
        atb = get_atb_generation(
            cfg.data_cache_config,
            sorted(
                {
                    name
                    for t in GenerationTechnology
                    if (name := t.get_atb_display_name()) is not None
                }
            ),
            cfg.atb_scenario,
        )
        logger.debug(
            f"Loaded {len(units)} CODERS generating units, {len(generic)} generic "
            + f"types and {len(atb)} ATB values"
        )
        # TODO: CODERS (storage, reserve, interties, demand), new VRE bins, IESO,
        # StatCan, renewables.ninja, ramp rates

        # Compute parameters
        # ------------------
        # - Grid: transmission to distribution efficiency (region), variable cost
        #   (level, period) in M$/PJ read at price_projection_point, and the
        #   lifetime of the single vintage of the pass-through technologies
        transmission = transmission_efficiencies(line_losses, cfg.provinces)
        projection_years = projection_year_by_period(
            cfg.future_periods, cfg.period_step, cfg.price_projection_point
        )
        costs = grid_variable_costs(
            grid_costs,
            projection_years,
            currency_conversion_factor(
                grid_costs.currency,
                grid_costs.currency_year,
                cfg.model_currency_year,
                exchange,
                inflation,
            ),
        )
        # Single vintage (the first period) serving every period
        lifetime = horizon_length(cfg.future_periods, cfg.period_step)

        # - Existing generation: CODERS units grouped by (region, technology,
        #   vintage), lifetimes, efficiencies, O&M costs (M$ of model_currency_year)
        #   and the activity bounds of cogeneration
        existing_generation: ExistingGeneration | None = None
        if not cfg.generation.skip_existing:
            lifetimes = existing_lifetimes(generic)
            fleet = existing_generators(
                units,
                cfg.provinces,
                lifetimes,
                cfg.future_periods[0],
                cfg.period_step,
                cfg.generation.existing_capacity_threshold,
            )
            check_missing_existing_periods(
                db_conn,
                sorted({int(v) for v in fleet["vintage"]}),
                cfg.validation_behavior,
            )
            existing_generation = build_existing_generation(
                fleet,
                lifetimes,
                existing_efficiencies(fleet, generic, atb),
                existing_om_costs(
                    fleet,
                    generic,
                    atb,
                    lifetimes,
                    cfg.future_periods,
                    atb_conversion=currency_conversion_factor(
                        "USD",
                        cfg.source_years.atb_currency,
                        cfg.model_currency_year,
                        exchange,
                        inflation,
                    ),
                    coders_conversion=currency_conversion_factor(
                        "CAD",
                        cfg.source_years.coders_currency,
                        cfg.model_currency_year,
                        exchange,
                        inflation,
                    ),
                ),
                cogeneration_activity(
                    fleet,
                    lifetimes,
                    cfg.future_periods,
                    cfg.generation.cogeneration_floor,
                ),
                _existing_generation_notes(cfg),
                electricity_data_id,
            )
            logger.debug(
                f"Existing generation: {len(fleet)} (region, technology, vintage), "
                + f"{fleet['capacity'].sum():.1f} GW"
            )
        # TODO: new generation, capacity factors, storage, CCS, reliability, trade

        # Build TEMOA Objects
        # -------------------
        # Write data_id labels (first because they impact everything)
        datasets = [
            DataSet(data_id=electricity_data_id.get_dataset_code(province=province))
            for province in cfg.provinces + [None]
        ]
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            datasets, include_nulls=True, include_defaults=True
        )
        db_conn.executemany(sql, params)

        # Grid commodities and technologies, and the delivery to each sector
        grid = build_grid(
            transmission,
            costs,
            imports,
            first_period=cfg.future_periods[0],
            lifetime=lifetime,
            cost_notes=_cost_notes(cfg, grid_costs.reference),
            data_id=electricity_data_id,
        )
        logger.info(
            f"Building the grid of {len(transmission)} provinces and "
            + f"{len(grid.deliveries)} delivery technologies"
        )
        grid.build(db_conn)

        # Existing generators, and the fuels they burn for the fuel module
        generator_imports: list[CANOEFuelImport] = []
        if existing_generation is not None:
            logger.info(
                f"Building {len(existing_generation.technologies)} existing "
                + "generation technologies"
            )
            existing_generation.build(db_conn)
            generator_imports = declare_fuel_imports(
                CANOESector.Electricity, existing_generation.technologies
            )
        # TODO: new generators, storage, CCS retrofits, interties

    return CANOEModuleOutput(fuel_imports=generator_imports)


def _cost_notes(cfg: "CANOEElectricityConfig", reference: str) -> str:
    point = {
        ProjectionPoint.PeriodEnd: "the end of each period",
        ProjectionPoint.PeriodStart: "the label year of each period",
    }[cfg.price_projection_point]
    return (
        f"{reference}, read at {point}, in M$/PJ of {cfg.model_currency_year} CAD "
        + "(GDP deflator)"
    )


def _existing_generation_notes(
    cfg: "CANOEElectricityConfig",
) -> ExistingGenerationNotes:
    to_model = f"to {cfg.model_currency_year} CAD (GDP deflator)"
    atb = (
        f"NREL ATB 2024 ({cfg.atb_scenario}, market case) at the vintage year, "
        + "2022 at the earliest"
    )
    return ExistingGenerationNotes(
        capacity=f"CODERS generators (cache {cfg.data_cache_config.cache_date}): "
        + "units by last renewal (or start) year, rounded to "
        + f"{cfg.period_step}-year vintages before {cfg.future_periods[0]}; groups "
        + f"of {cfg.generation.existing_capacity_threshold} GW or less left out",
        atb_costs=f"{atb}, {cfg.source_years.atb_currency} USD {to_model}",
        coders_costs=f"CODERS generation_generic, {cfg.source_years.coders_currency} "
        + f"CAD {to_model}",
        atb_efficiency=atb,
        cogeneration="CODERS average annual output of the surviving units. The "
        + "model does not represent the heat the host sites need, so the output is "
        + f"held between {cfg.generation.cogeneration_floor} and 1 times its "
        + "historical level",
    )


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

# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

import pandas as pd
from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import (
    CANOEEmission,
    CANOEEmissionDeclaration,
    CANOEFuel,
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.currency import currency_conversion_factor
from canoe.common.loaders import (
    get_combustion_emission_factors,
    get_exchange_and_inflation_tables,
)
from canoe.common.naming import DatasetIdentifier
from canoe.common.periods import (
    ProjectionPoint,
    horizon_length,
    projection_year_by_period,
)
from canoe.common.validation import check_missing_existing_periods

from .catalogue import CCSRetrofit, GenerationTechnology, StorageTechnology
from .fleet import (
    existing_generators,
    existing_storage,
    existing_storage_units,
    existing_units,
)
from .generation.capacity_factors import existing_capacity_factors
from .generation.ccs import (
    electricity_co2_factors,
    generator_capture_factors,
    retrofit_capture_factors,
    retrofit_efficiencies,
    retrofit_om_costs,
    retrofit_processes,
)
from .generation.entities import (
    CarbonCapture,
    GenerationEntities,
    GenerationNotes,
    Reliability,
    build_ccs_retrofits,
    build_existing_generation,
    build_new_generation,
    build_vre_bins,
    retrofit_intermediate_commodity,
)
from .generation.parameters import (
    cogeneration_activity,
    existing_processes,
    generation_lifetimes,
    new_processes,
    process_efficiencies,
    process_investment_costs,
    process_om_costs,
    vre_bin_capacity_factors,
    vre_bin_costs,
    vre_bin_limits,
)
from .loaders import (
    get_aeo_transmission_distribution_costs,
    get_atb_generation,
    get_coders_generation_generic,
    get_coders_generators,
    get_coders_reserve_margins,
    get_coders_storage,
    get_coders_system_line_losses,
    get_ieso_generator_output,
    get_ieso_hydro_types,
    get_ieso_output_by_fuel,
    get_ieso_summer_peak_capability,
    get_ramp_rates,
    get_renewables_ninja_facility_profiles,
    get_statcan_monthly_hydro,
    get_vre_bin_capacity_credits,
    get_vre_bin_capacity_factors,
    get_vre_bin_capacity_limits,
    get_vre_bin_fixed_costs,
    get_vre_bin_investment_costs,
)
from .reliability import (
    ieso_capacity_ratios,
    planning_reserve_margins,
    process_capacity_credits,
    process_reserve_derates,
    vre_bin_capacity_credits,
)
from .storage.entities import build_existing_storage, build_new_storage
from .storage.parameters import storage_efficiencies, storage_lifetimes
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
                    for t in [*GenerationTechnology, *StorageTechnology, *CCSRetrofit]
                    if (name := t.get_atb_display_name()) is not None
                }
            ),
            cfg.atb_scenario,
        )
        logger.debug(
            f"Loaded {len(units)} CODERS generating units, {len(generic)} generic "
            + f"types and {len(atb)} ATB values"
        )
        # Storage: CODERS storage facilities (MW, hours)
        storage_units = get_coders_storage(cfg.data_cache_config)
        # Weather of the existing wind, solar and hydro: IESO hourly output (MWh, MW),
        # StatCan monthly hydro (MWh), renewables.ninja profiles (capacity factors)
        years = cfg.source_years
        output_by_fuel = get_ieso_output_by_fuel(years.ieso_hourly)
        generator_output = get_ieso_generator_output(years.ieso_hourly)
        hydro_types = get_ieso_hydro_types()
        monthly_hydro = get_statcan_monthly_hydro(years.statcan_monthly_hydro)
        facility_profiles = get_renewables_ninja_facility_profiles(
            years.renewables_ninja
        )
        # New wind and solar bins (2021 USD, GW, hourly capacity factors), only if
        # modelled
        binned = [t for t in cfg.generation.new_technologies if t.is_resource_binned()]
        bin_investment = bin_fixed = bin_limits = bin_factors = None
        if binned:
            bin_investment = get_vre_bin_investment_costs(cfg.data_cache_config)
            bin_fixed = get_vre_bin_fixed_costs(cfg.data_cache_config)
            bin_limits = get_vre_bin_capacity_limits(cfg.data_cache_config)
            bin_factors = get_vre_bin_capacity_factors(cfg.data_cache_config)
        # Carbon capture: CO2 of burning each fuel (kt/PJ), shared with the fuel module
        combustion_factors = get_combustion_emission_factors()
        # Reliability: CODERS planning reserve margins (fraction), IESO capability at
        # the summer peak by fuel (MW), capacity credits of the wind and solar bins;
        # ramp rates (fraction of capacity per hour) whether or not
        reliability = cfg.reliability
        margins = capability = bin_credits = None
        if not reliability.skip:
            margins = get_coders_reserve_margins()
            capability = get_ieso_summer_peak_capability(years.ieso_reliability_outlook)
            if binned:
                bin_credits = get_vre_bin_capacity_credits(cfg.data_cache_config)
        ramp_rates = get_ramp_rates()
        # TODO: CODERS (interties, demand)

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

        # - Generation: lifetimes and currency factors to M$ of model_currency_year
        lifetimes = generation_lifetimes(generic)
        atb_conversion = currency_conversion_factor(
            "USD",
            cfg.source_years.atb_currency,
            cfg.model_currency_year,
            exchange,
            inflation,
        )
        coders_conversion = currency_conversion_factor(
            "CAD",
            cfg.source_years.coders_currency,
            cfg.model_currency_year,
            exchange,
            inflation,
        )
        notes = _generation_notes(cfg)

        # - Carbon capture: the retrofitted generators output to the intermediate
        #   commodity of their retrofits; those built with capture capture part of
        #   the CO2 of their fuel
        retrofits = list(cfg.generation.ccs_retrofits)
        co2_factors = electricity_co2_factors(combustion_factors)
        capture = CarbonCapture(
            outputs={
                generator: retrofit_intermediate_commodity(generator)
                for generator in dict.fromkeys(r.get_generator() for r in retrofits)
            },
            factors=generator_capture_factors(list(GenerationTechnology), co2_factors),
        )

        # - Reliability: the share of each generator's capacity available at the
        #   summer peak (Ontario's, by fuel), as capacity credits and derates; none if
        #   the reserve margin is left out
        ratios = (
            {}
            if capability is None
            else ieso_capacity_ratios(capability, reliability.ieso_peak_type)
        )

        # - Existing generation: CODERS units grouped by (region, technology,
        #   vintage), efficiencies, O&M costs, the activity bounds of cogeneration
        #   (the ATB is read at the vintage year), and the capacity factors of the
        #   weather-driven ones
        existing_generation: GenerationEntities | None = None
        fleet = pd.DataFrame(columns=["region", "technology", "vintage"])
        if not cfg.generation.skip_existing:
            fleet_units = existing_units(
                units, cfg.provinces, cfg.future_periods[0], cfg.period_step
            )
            fleet = existing_generators(
                fleet_units,
                lifetimes,
                cfg.future_periods[0],
                cfg.generation.existing_capacity_threshold,
            )
            hourly_factors, daily_limits = existing_capacity_factors(
                fleet,
                # The units of the groups kept
                fleet_units.merge(
                    fleet[["region", "technology", "vintage"]],
                    on=["region", "technology", "vintage"],
                ),
                output_by_fuel,
                generator_output,
                hydro_types,
                monthly_hydro,
                facility_profiles,
                years.ieso_hourly,
                years.statcan_monthly_hydro,
                cfg.generation.capacity_factor_tolerance,
            )
            check_missing_existing_periods(
                db_conn,
                sorted({int(v) for v in fleet["vintage"]}),
                cfg.validation_behavior,
            )
            existing = existing_processes(fleet)
            existing_generation = build_existing_generation(
                fleet,
                lifetimes,
                process_efficiencies(existing, generic, atb),
                process_om_costs(
                    existing,
                    generic,
                    atb,
                    lifetimes,
                    cfg.future_periods,
                    atb_conversion,
                    coders_conversion,
                ),
                cogeneration_activity(
                    fleet,
                    lifetimes,
                    cfg.future_periods,
                    cfg.generation.cogeneration_floor,
                ),
                hourly_factors,
                daily_limits,
                capture,
                notes,
                electricity_data_id,
                Reliability(
                    credits=process_capacity_credits(
                        existing, ratios, lifetimes, cfg.future_periods
                    ),
                    derates=process_reserve_derates(
                        existing,
                        ratios,
                        reliability.reproduce_previous_hydro_storage_derate,
                    ),
                    ramp_rates=ramp_rates,
                ),
            )
            logger.debug(
                f"Existing generation: {len(fleet)} (region, technology, vintage), "
                + f"{fleet['capacity'].sum():.1f} GW"
            )

        # - New generation: one vintage per period in every province, the ATB read
        #   at the projection year of the period (price_projection_point)
        new = new_processes(
            [t for t in cfg.generation.new_technologies if not t.is_resource_binned()],
            cfg.provinces,
            projection_years,
        )
        new_generation = build_new_generation(
            process_efficiencies(new, generic, atb),
            process_investment_costs(new, atb, atb_conversion),
            process_om_costs(
                new,
                generic,
                atb,
                lifetimes,
                cfg.future_periods,
                atb_conversion,
                coders_conversion,
            ),
            lifetimes,
            capture,
            notes,
            electricity_data_id,
            Reliability(
                credits=process_capacity_credits(
                    new, ratios, lifetimes, cfg.future_periods
                ),
                derates=process_reserve_derates(
                    new, ratios, reliability.reproduce_previous_hydro_storage_derate
                ),
                ramp_rates=ramp_rates,
            ),
        )

        # - New wind and solar bins: their costs, capacity limits and capacity credits
        vre_bins: GenerationEntities | None = None
        if (
            bin_investment is not None
            and bin_fixed is not None
            and bin_limits is not None
            and bin_factors is not None
        ):
            bins_conversion = currency_conversion_factor(
                bin_investment.currency,
                bin_investment.currency_year,
                cfg.model_currency_year,
                exchange,
                inflation,
            )
            investment, fixed = vre_bin_costs(
                bin_investment.costs,
                bin_fixed.costs,
                binned,
                cfg.provinces,
                cfg.future_periods,
                lifetimes,
                bins_conversion,
            )
            vre_bins = build_vre_bins(
                investment,
                fixed,
                vre_bin_limits(bin_limits, binned, cfg.provinces, cfg.future_periods),
                vre_bin_capacity_factors(
                    bin_factors,
                    binned,
                    cfg.provinces,
                    cfg.future_periods,
                    cfg.generation.capacity_factor_tolerance,
                ),
                lifetimes,
                notes,
                electricity_data_id,
                None
                if bin_credits is None
                else vre_bin_capacity_credits(
                    bin_credits, binned, cfg.provinces, cfg.future_periods
                ),
            )
        # - Storage: existing CODERS facilities grouped as the generators, new storage
        #   in every province; round-trip efficiencies from the config, costs as the
        #   generators'
        storage_lives = storage_lifetimes(generic)
        storage: list[TechnologyEntity] = []
        if not cfg.storage.skip_existing:
            storage_fleet = existing_storage(
                existing_storage_units(
                    storage_units, cfg.provinces, cfg.future_periods[0], cfg.period_step
                ),
                storage_lives,
                cfg.future_periods[0],
                cfg.generation.existing_capacity_threshold,
            )
            check_missing_existing_periods(
                db_conn,
                sorted({int(v) for v in storage_fleet["vintage"]}),
                cfg.validation_behavior,
            )
            existing_stores = existing_processes(storage_fleet)
            storage += build_existing_storage(
                storage_fleet,
                storage_efficiencies(
                    existing_stores,
                    cfg.storage.battery_round_trip_efficiency,
                    cfg.storage.pumped_hydro_round_trip_efficiency,
                ),
                process_om_costs(
                    existing_stores,
                    generic,
                    atb,
                    storage_lives,
                    cfg.future_periods,
                    atb_conversion,
                    coders_conversion,
                ),
                storage_lives,
                notes,
                electricity_data_id,
            )
        new_stores = new_processes(
            list(cfg.storage.new_technologies), cfg.provinces, projection_years
        )
        storage += build_new_storage(
            storage_efficiencies(
                new_stores,
                cfg.storage.battery_round_trip_efficiency,
                cfg.storage.pumped_hydro_round_trip_efficiency,
            ),
            process_investment_costs(new_stores, atb, atb_conversion),
            process_om_costs(
                new_stores,
                generic,
                atb,
                storage_lives,
                cfg.future_periods,
                atb_conversion,
                coders_conversion,
            ),
            storage_lives,
            notes,
            electricity_data_id,
        )

        # - CCS retrofits: where a generator can be retrofitted, their efficiency
        #   penalty and costs (ATB at the projection year of the vintage), and the CO2
        #   they capture with the configured heat rates of the generators
        ccs_retrofits: GenerationEntities | None = None
        if retrofits:
            retrofitted, bypasses = retrofit_processes(
                fleet,
                retrofits,
                list(cfg.generation.new_technologies),
                cfg.provinces,
                projection_years,
                lifetimes,
            )
            ccs_retrofits = build_ccs_retrofits(
                retrofitted,
                bypasses,
                retrofit_efficiencies(retrofitted, atb),
                process_investment_costs(
                    retrofitted, atb, atb_conversion, metric="Additional OCC"
                ),
                retrofit_om_costs(retrofitted, atb, cfg.future_periods, atb_conversion),
                retrofit_capture_factors(
                    retrofits, co2_factors, cfg.generation.ccs_retrofit_heat_rates
                ),
                notes,
                electricity_data_id,
            )
        # TODO: trade

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
            reserve_margins=None
            if margins is None
            else planning_reserve_margins(margins, cfg.provinces),
        )
        logger.info(
            f"Building the grid of {len(transmission)} provinces and "
            + f"{len(grid.deliveries)} delivery technologies"
        )
        grid.build(db_conn)

        # Generators: CCS retrofits first (the retrofitted generators output to their
        # intermediate commodity), existing, new and the wind and solar bins
        generation = {
            "CCS retrofit and bypass": ccs_retrofits,
            "existing": existing_generation,
            "new": new_generation,
            "wind and solar bin": vre_bins,
        }
        generators: list[TechnologyEntity] = []
        for kind, entities in generation.items():
            if entities is None:
                continue
            logger.info(
                f"Building {len(entities.technologies)} {kind} generation "
                + "technologies"
            )
            entities.build(db_conn)
            generators += entities.technologies

        # Storage
        logger.info(f"Building {len(storage)} storage technologies")
        for technology in storage:
            technology.build(db_conn)
        # TODO: interties

    # The fuels the generators burn, for the fuel module, and the CO2 captured
    captures = any(t.input_emission_factors for t in generators)
    return CANOEModuleOutput(
        fuel_imports=declare_fuel_imports(CANOESector.Electricity, generators),
        emissions=[CANOEEmissionDeclaration(CANOESector.Electricity, CANOEEmission.CO2)]
        if captures
        else [],
    )


def _cost_notes(cfg: "CANOEElectricityConfig", reference: str) -> str:
    point = {
        ProjectionPoint.PeriodEnd: "the end of each period",
        ProjectionPoint.PeriodStart: "the label year of each period",
    }[cfg.price_projection_point]
    return (
        f"{reference}, read at {point}, in M$/PJ of {cfg.model_currency_year} CAD "
        + "(GDP deflator)"
    )


def _generation_notes(cfg: "CANOEElectricityConfig") -> GenerationNotes:
    years = cfg.source_years
    to_model = f"to {cfg.model_currency_year} CAD (GDP deflator)"
    point = {
        ProjectionPoint.PeriodEnd: "the end",
        ProjectionPoint.PeriodStart: "the label year",
    }[cfg.price_projection_point]
    atb = (
        f"NREL ATB 2024 ({cfg.atb_scenario}, market case), existing vintages at their "
        + f"year, new ones at {point} of their period; 2022 at the earliest (2030 "
        + "for nuclear)"
    )
    ieso = (
        f"IESO Reliability Outlook {years.ieso_reliability_outlook}, Table 4.1: "
        + f"{cfg.reliability.ieso_peak_type.lower()} capability at summer peak over "
        + "installed capacity of the fuel type, Ontario's applied to every province"
    )
    return GenerationNotes(
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
        vre_bin_costs="NREL ATB 2023 (Moderate) at the end of the vintage's period, "
        + "by turbine class mix (wind), plus spur line costs (Sutubra, 2024); 2021 "
        + f"USD {to_model}",
        vre_bin_limits="Wind and solar resource (Sutubra, 2024): grid cells binned "
        + "by ascending LCOE",
        vre_bin_capacity_factors="Hourly profile of the bin (Sutubra, 2024; 2018 "
        + "weather), indexed to NREL ATB 2023 by construction year; hours missing "
        + "from the source are 0",
        vre_capacity_factors=f"Ontario: IESO {years.ieso_hourly} hourly output by "
        + "fuel, scaled to the CODERS capacity-weighted capacity factor of units over "
        + "20 MW; other provinces: renewables.ninja "
        + f"{years.renewables_ninja} profiles at each CODERS facility, weighted by "
        + "capacity and scaled to CODERS annual energy",
        hydro_capacity_factors=f"Ontario: IESO {years.ieso_hourly} output over "
        + "available capacity of the generators of each hydro type; other "
        + f"provinces: StatCan 25-10-0015-01 {years.statcan_monthly_hydro} monthly "
        + "hydro generation, flat within the month, shared between hydro types by "
        + "CODERS annual energy",
        capture="minus the capture rate times the CO2 combustion factor of the fuel "
        + "(electricity sector, shared with the fuel module, which accounts the "
        + "emissions); retrofits per unit of the generator's electricity, with the "
        + "configured generator heat rate (ccs_retrofit_heat_rates)",
        capacity_credits=f"{ieso}; the share of capacity counted in each period",
        reserve_derates=f"{ieso}; the share of available output counted in each "
        + "season",
        vre_bin_capacity_credits="NREL ReEDS method (Frew et al., 2017): reduction of "
        + "the top 100 hours of the net load duration curve per unit of capacity, "
        + "bins built out in order of LCOE, one technology at a time (Sutubra, 2024; "
        + "2018 load and weather)",
        ramp_rates="Fraction of capacity per hour, up and down: Dolter & Rivers "
        + "(2018), The cost of decarbonizing the Canadian electricity system, SI "
        + "Table 7",
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

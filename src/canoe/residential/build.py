# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

import pandas as pd
from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.common import (
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.currency import currency_conversion_factor
from canoe.common.gdp import GDPProjectionPoint
from canoe.common.loaders import get_cer_gdp, get_exchange_and_inflation_tables
from canoe.common.naming import DatasetIdentifier
from canoe.common.periods import period_end_years
from canoe.common.weather_maps import load_weather_maps

from .appliances import appliance_stock
from .ceud import load_ceud_tables
from .demand import (
    DemandDriver,
    gdp_growth,
    population_by_year,
    population_growth,
    project_demand,
)
from .dsd import demand_specific_distributions
from .end_uses import ResidentialEndUse
from .entities import (
    ResidentialEntities,
    build_end_use_demand,
    build_existing_technologies,
    build_new_technologies,
    build_other_appliances,
)
from .existing_stock import (
    EndUseStock,
    aeo_class_lifetimes,
    equivalent_fixed_costs,
    equivalent_lifetimes,
    existing_vintages,
)
from .lighting import lighting_stock
from .loaders import (
    get_aeo_lighting_data,
    get_aeo_technology_menu,
    get_handbook_appliance_consumption,
    get_ontario_lighting_shares,
    get_statcan_energy_saving_lights,
    get_statcan_population_estimates,
    get_statcan_population_projections,
)
from .new_technologies import new_technology_parameters
from .profiles import load_resstock_consumption
from .space_cooling import space_cooling_stock
from .space_heating import space_heating_stock
from .technology_catalog import ExistingTechnology
from .validation import validate_db_against_config, validate_existing_vintages
from .water_heating import water_heating_stock

if TYPE_CHECKING:
    from .config import CANOEResidentialConfig


def build_residential(cfg: "CANOEResidentialConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE residential sector.

    Units: PJ for energy services, Glmy for lighting and Munity for appliances, the
    units of the data; capacity in kunit, Glm and Munit; costs in M$ of the model
    currency year.
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
        end_uses = cfg.end_uses.enabled()
        # NRCan CEUD: base-year energy use, stock and efficiencies of each province
        ceud = load_ceud_tables(cfg.provinces, cfg.ceud_data_year)
        # NRCan handbook: unit energy consumption of the appliance stock
        appliance_consumption = (
            get_handbook_appliance_consumption(cfg.data_cache_config)
            if ResidentialEndUse.ClothesDryers in end_uses
            or ResidentialEndUse.CookingRanges in end_uses
            else None
        )
        # AEO: equipment classes (lifetimes, base efficiencies) and new equipment
        # (efficiencies, costs) by census division, and the currency tables to
        # convert its costs
        aeo_menu = get_aeo_technology_menu()
        exchange, inflation = get_exchange_and_inflation_tables()
        # Lighting: AEO lamp data, Ontario bulb shares and the use of energy-saving
        # lights by province (relative to Ontario, always read)
        lighting = ResidentialEndUse.Lighting in end_uses
        aeo_lighting = get_aeo_lighting_data() if lighting else None
        ontario_lighting_shares = get_ontario_lighting_shares() if lighting else None
        energy_saving_lights = (
            get_statcan_energy_saving_lights(
                list(dict.fromkeys([*cfg.provinces, CANOEProvince.ONTARIO]))
            )
            if lighting
            else None
        )
        # ResStock hourly energy use per household and the weather maps of the
        # provinces, for the demand-specific distributions
        resstock = (
            load_resstock_consumption(
                cfg.resstock_us_states, cfg.provinces, cfg.data_cache_config
            )
            if cfg.include_dsd
            else {}
        )
        weather_maps = (
            load_weather_maps(cfg.provinces, cfg.data_cache_config)
            if cfg.include_dsd and any(cfg.end_uses.weather_mapping().values())
            else {}
        )
        logger.debug(
            f"Loaded residential data of {len(cfg.provinces)} provinces: CEUD "
            + f"{cfg.ceud_data_year} ("
            + f"{ceud.space_heating_energy_use['energy_use'].sum():.1f} PJ of space "
            + "heating); handbook ("
            + f"{0 if appliance_consumption is None else len(appliance_consumption)} "
            + f"appliances); AEO menu ({len(aeo_menu.classes)} classes, "
            + f"{len(aeo_menu.equipment)} equipment rows, {aeo_menu.cost_dollar_year} "
            + f"USD); currency tables ({len(exchange)} and {len(inflation)} years); "
            + "lighting ("
            + ", ".join(
                f"{len(df)} rows"
                for df in (aeo_lighting, ontario_lighting_shares, energy_saving_lights)
                if df is not None
            )
            + f"); {len(resstock)} ResStock tables; {len(weather_maps)} weather maps"
        )

        # Compute parameters
        # ------------------
        model_periods = cfg.future_periods
        first_period = model_periods[0]
        # Vintages read the data of the year their period ends
        data_years = period_end_years(model_periods, cfg.period_step)
        currency_factor = currency_conversion_factor(
            "USD",
            aeo_menu.cost_dollar_year,
            cfg.model_currency_year,
            exchange,
            inflation,
        )
        class_lifetimes = aeo_class_lifetimes(aeo_menu.classes)
        # - Growth of the demands from the CEUD data year to each period, and to the
        #   start of the first period (when the existing stock stands), driven by
        #   provincial population (StatCan) or national GDP (CER)
        if cfg.demand_driver == DemandDriver.Population:
            population = population_by_year(
                get_statcan_population_estimates(),
                get_statcan_population_projections(),
                cfg.provinces,
            )
            growth, stock_growth = (
                population_growth(
                    population,
                    cfg.provinces,
                    cfg.ceud_data_year,
                    model_periods,
                    cfg.period_step,
                    cfg.demand_projection_point,
                ),
                population_growth(
                    population,
                    cfg.provinces,
                    cfg.ceud_data_year,
                    [first_period],
                    cfg.period_step,
                    GDPProjectionPoint.PeriodStart,
                ),
            )
        else:
            gdp_index = get_cer_gdp(
                cfg.data_cache_config,
                gdp_index_year=cfg.ceud_data_year,
                scenario=cfg.gdp_scenario,
            )
            growth, stock_growth = (
                gdp_growth(
                    gdp_index,
                    cfg.provinces,
                    model_periods,
                    cfg.period_step,
                    cfg.demand_projection_point,
                ),
                gdp_growth(
                    gdp_index,
                    cfg.provinces,
                    [first_period],
                    cfg.period_step,
                    GDPProjectionPoint.PeriodStart,
                ),
            )
        # - Existing technologies (lamps and other appliances aside): lifetime and
        #   fixed cost of their equivalent new technology, vintages of their stock
        existing = [
            t
            for t in ExistingTechnology
            if t.spec().end_use in end_uses
            and t.spec().lamp is None
            and t != ExistingTechnology.OtherAppliances
        ]
        lifetimes = equivalent_lifetimes(existing, class_lifetimes)
        vintages = existing_vintages(lifetimes, first_period, cfg.period_step)
        stock_args = (
            vintages,
            pd.DataFrame(
                {"technology": list(lifetimes), "lifetime": list(lifetimes.values())}
            ),
            equivalent_fixed_costs(existing, currency_factor),
            cfg.provinces,
            model_periods,
            cfg.existing_capacity_tolerance,
            cfg.ceud_data_year,
        )
        # - Existing stock and base-year demand of each group of end uses
        stocks: list[EndUseStock] = []
        if ResidentialEndUse.SpaceHeating in end_uses:
            stocks.append(
                space_heating_stock(
                    ceud.space_heating_energy_use,
                    ceud.heating_system_stock,
                    ceud.heating_system_efficiencies,
                    *stock_args,
                )
            )
        if ResidentialEndUse.SpaceCooling in end_uses:
            stocks.append(
                space_cooling_stock(
                    ceud.space_cooling_energy_use,
                    ceud.cooling_system_stock,
                    ceud.cooling_system_efficiencies,
                    *stock_args,
                )
            )
        if ResidentialEndUse.WaterHeating in end_uses:
            stocks.append(
                water_heating_stock(
                    ceud.water_heating_energy_use,
                    ceud.water_heater_stock,
                    aeo_menu.classes,
                    *stock_args,
                )
            )
        appliances = (
            appliance_stock(
                ceud.appliance_energy_use,
                ceud.appliance_stock,
                appliance_consumption,
                cfg.end_uses.appliances.annual_capacity_factor,
                *stock_args,
            )
            if cfg.end_uses.appliances is not None
            else None
        )
        if appliances is not None:
            stocks.append(appliances.stock)
        lighting_stock_ = (
            lighting_stock(
                ceud.lighting_energy_use,
                ceud.household_shares,
                aeo_lighting,
                ontario_lighting_shares,
                energy_saving_lights,
                stock_growth.loc[:, ["region", "growth"]],
                [t for t in new_technologies if t.spec().lamp is not None],
                cfg.end_uses.lighting.annual_capacity_factor,
                currency_factor,
                cfg.provinces,
                model_periods,
                cfg.period_step,
                data_years,
                cfg.existing_capacity_tolerance,
                cfg.ceud_data_year,
            )
            if cfg.end_uses.lighting is not None
            and aeo_lighting is not None
            and ontario_lighting_shares is not None
            and energy_saving_lights is not None
            else None
        )
        if lighting_stock_ is not None:
            stocks.append(lighting_stock_.stock)
        validate_existing_vintages(
            cfg,
            db_conn,
            sorted(
                {
                    int(v)
                    for stock in stocks
                    for v in stock.parameters.existing_capacity["vintage"]
                }
            ),
        )
        # - New AEO technologies (lamps are in the lighting stock)
        new_parameters = new_technology_parameters(
            new_technologies,
            aeo_menu.equipment,
            aeo_menu.classes,
            cfg.aeo_census_divisions,
            pd.concat([s.capacity_factor for s in stocks], ignore_index=True),
            appliances.stock.parameters.efficiency
            if appliances is not None
            else pd.DataFrame(
                columns=["region", "technology", "vintage", "fuel", "efficiency"]
            ),
            class_lifetimes,
            currency_factor,
            cfg.provinces,
            model_periods,
            data_years,
        )
        # - Demands: base-year demand times growth
        demand_df = project_demand(
            pd.concat([s.base_demand for s in stocks], ignore_index=True), growth
        )
        demand_notes = {
            end_use: f"{s.demand_notes} ({_driver_notes(cfg.demand_driver)})"
            for s in stocks
            for end_use in s.base_demand["end_use"].unique()
        }
        # - Demand-specific distributions
        dsd_df = (
            demand_specific_distributions(
                resstock,
                ceud.household_shares,
                cfg.resstock_us_states,
                weather_maps,
                cfg.end_uses.weather_mapping(),
                cfg.provinces,
                cfg.dsd_tolerance,
            )
            if cfg.include_dsd
            else None
        )

        # Build TEMOA Objects
        # -------------------
        # Write data_id labels (first because they impact everything)
        datasets = [
            DataSet(data_id=sector_data_id.get_dataset_code(province=province))
            for province in cfg.provinces + [None]
        ]
        sql, params = DataSet.bulk_insert_or_ignore_sql(
            datasets, include_nulls=True, include_defaults=True
        )
        db_conn.executemany(sql, params)

        # Demands first (the technologies output them), then the technologies
        entities = ResidentialEntities(
            demands=[
                build_end_use_demand(
                    end_use,
                    demand_df,
                    dsd_df,
                    cfg.provinces,
                    model_periods,
                    cfg.dsd_time_slices.as_list(),
                    demand_notes=demand_notes[end_use],
                    dsd_notes=_dsd_notes(cfg.end_uses.weather_mapping()[end_use]),
                    data_id=sector_data_id,
                )
                for end_use in end_uses
            ],
            existing_technologies=[
                entity
                for stock in stocks
                for entity in build_existing_technologies(
                    stock.technologies,
                    stock.parameters,
                    cfg.provinces,
                    model_periods,
                    sector_data_id,
                )
            ],
            other_appliances=build_other_appliances(
                appliances.other_appliances_efficiency,
                cfg.provinces,
                first_period,
                notes="Appliances in use (stock times the annual capacity factor) over "
                + f"energy use (NRCan CEUD tables 13 and 31, {cfg.ceud_data_year})",
                data_id=sector_data_id,
                lifetime=cfg.end_uses.appliances.other_appliances_lifetime,
            )
            if appliances is not None and cfg.end_uses.appliances is not None
            else None,
            new_technologies=[
                *build_new_technologies(
                    [t for t in new_technologies if t.spec().lamp is None],
                    new_parameters,
                    cfg.provinces,
                    model_periods,
                    sector_data_id,
                ),
                *(
                    build_new_technologies(
                        [t for t in new_technologies if t.spec().lamp is not None],
                        lighting_stock_.new_lamps,
                        cfg.provinces,
                        model_periods,
                        sector_data_id,
                    )
                    if lighting_stock_ is not None
                    else []
                ),
            ],
        )
        logger.info(
            f"Building {len(entities.demands)} residential demands, "
            + f"{len(entities.existing_technologies)} existing and "
            + f"{len(entities.new_technologies)} new technologies"
        )
        entities.build(db_conn)

    # The fuels the technologies take, where they take them
    return CANOEModuleOutput(fuel_imports=entities.fuel_imports())


def _driver_notes(driver: DemandDriver) -> str:
    return {
        DemandDriver.Population: "provincial population, StatCan estimates and "
        + "projections (M1)",
        DemandDriver.GDP: "national GDP, CER Canada's Energy Future 2023",
    }[driver]


def _dsd_notes(weather_mapped: bool) -> str:
    mapping = (
        " mapped from the state's weather to the province's (Renewables Ninja, 2018)"
        if weather_mapped
        else ""
    )
    return (
        "ResStock hourly energy use per household of the comparable US state (NREL, "
        + "amy2018, upgrade 16), weighed by households by building type (NRCan CEUD "
        + f"table 14){mapping}; hours below the tolerance set to 0"
    )

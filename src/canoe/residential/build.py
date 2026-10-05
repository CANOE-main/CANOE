# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.common import (
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    atomic_transaction,
)
from canoe.common.loaders import get_cer_gdp, get_exchange_and_inflation_tables
from canoe.common.naming import DatasetIdentifier
from canoe.common.weather_maps import load_weather_maps

from .ceud import load_ceud_tables
from .demand import DemandDriver, population_by_year
from .end_uses import ResidentialEndUse
from .loaders import (
    get_aeo_lighting_data,
    get_aeo_technology_menu,
    get_handbook_appliance_consumption,
    get_ontario_lighting_shares,
    get_statcan_energy_saving_lights,
    get_statcan_population_estimates,
    get_statcan_population_projections,
)
from .profiles import load_resstock_consumption
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
        # Demand driver: provincial population (StatCan) or national GDP (CER),
        # indexed later to the CEUD data year
        driver = (
            population_by_year(
                get_statcan_population_estimates(),
                get_statcan_population_projections(),
                cfg.provinces,
            )
            if cfg.demand_driver == DemandDriver.Population
            else get_cer_gdp(
                cfg.data_cache_config,
                gdp_index_year=cfg.ceud_data_year,
                scenario=cfg.gdp_scenario,
            )
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
            + f"); {cfg.demand_driver.value} by year ({len(driver)} rows); "
            + f"{len(resstock)} ResStock tables; {len(weather_maps)} weather maps"
        )

        # Compute parameters
        # ------------------
        # TODO: demands, existing stock, new technologies, lighting, DSDs

        # Build TEMOA Objects
        # -------------------
        # TODO: data sets; a demand per modelled end use
        # (`entities.build_end_use_demand`, from demand_df: region, period, end_use,
        # demand and dsd_df: region, end_use, season, tod, dsd); then the existing
        # technologies, new technologies and lighting

    return CANOEModuleOutput(fuel_imports=[])

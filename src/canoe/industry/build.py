# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from canoe_schema.v4_0 import DataSet
from loguru import logger

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier
from canoe.common.projections import (
    DemandProjectionPoint,
    get_gdp_table,
    growth_by_period,
    growth_notes,
)

from .demand import OtherFuelsTreatment, align_demand_and_splits, compute_demand
from .energy_use import (
    check_atlantic_shares,
    check_energy_use,
    compute_energy_use,
    compute_energy_use_by_source,
    load_ceud_tables,
)
from .entities import build_industry_entities
from .input_splits import compute_ceud_shares, compute_input_splits
from .loaders import get_statcan_atlantic_industry_shares
from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOEIndustryConfig


def build_industry(cfg: "CANOEIndustryConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE industry sector.

    Units hard-coded to PJ because that is the unit of the data.
    """
    logger.info(
        f"Running INDUSTRY (high-resolution) sector on {cfg.database_file}...\n"
    )

    sector_data_id: DatasetIdentifier = DatasetIdentifier(
        sector=CANOESector.Industry,
        code_description="HR",
        version=cfg.data_version,
    )
    logger.debug(f"Industry data set: {sector_data_id.get_dataset_code()}")
    subsectors = cfg.modelled_subsectors()
    own_fuels = {s: cfg.fuels_of(s) for s in subsectors if cfg.fuels_of(s) != cfg.fuels}
    logger.debug(
        f"Industry subsectors: {', '.join(s.short_desc() for s in subsectors)}; "
        + f"fuels: {', '.join(f.value for f in cfg.fuels)}"
        + "".join(
            f"; {s.short_desc()} fuels: {', '.join(f.value for f in fuels)}"
            for s, fuels in own_fuels.items()
        )
        + f"; other fuels: {cfg.other_fuels}"
    )

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # ----------------------------------
        # NRCan CEUD: energy use (PJ) of each subsector, total and by energy source,
        # with the Atlantic tables split among the Atlantic provinces by StatCan
        # shares
        ceud = load_ceud_tables(
            cfg.provinces, subsectors, cfg.ceud_data_year, cfg.data_cache_config
        )
        atlantic_shares = get_statcan_atlantic_industry_shares()
        check_atlantic_shares(ceud, atlantic_shares, cfg.missing_data_behavior)
        energy_use = compute_energy_use(ceud, atlantic_shares)
        energy_use_by_source = compute_energy_use_by_source(ceud, atlantic_shares)
        check_energy_use(energy_use, cfg.missing_data_behavior)
        # Projected GDP (national or by province, see `gdp`)
        gdp_table = get_gdp_table(cfg.gdp, cfg.data_cache_config)
        logger.debug(
            f"Loaded industry energy use of {len(subsectors)} subsectors in "
            + f"{len(cfg.provinces)} provinces ({energy_use['energy_use'].sum():.1f} "
            + f"PJ in {cfg.ceud_data_year}, {len(energy_use_by_source)} rows by "
            + f"source) and {len(gdp_table)} GDP projections"
        )

        # Compute parameters
        # ------------------
        # - Shares (province, subsector, fuel) of each source in the CEUD energy use,
        #   with the sources NRCan does not publish sharing the rest
        shares = compute_ceud_shares(energy_use_by_source)
        # - Demand (region, period, subsector): CEUD energy use (less "Other" fuels
        #   with other_fuels = "deduct") indexed to the projected gdp growth of the
        #   province
        gdp_growth = growth_by_period(
            gdp_table,
            cfg.provinces,
            cfg.ceud_data_year,
            cfg.future_periods,
            cfg.period_step,
            cfg.demand_projection_point,
        )
        demand_df = compute_demand(
            energy_use, energy_use_by_source, shares, gdp_growth, cfg.other_fuels
        )
        # - Input splits (region, period, subsector, fuel): the CEUD fuel mix, with
        #   the share of the sources a subsector does not model spread over its fuels
        input_fuels_of = {s: cfg.input_fuels_of(s) for s in subsectors}
        input_split_df = compute_input_splits(
            shares, input_fuels_of, cfg.future_periods
        )
        # Only where a subsector has both a demand and fuels to meet it
        demand_df, input_split_df = align_demand_and_splits(
            demand_df, input_split_df, cfg.missing_data_behavior
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

        # A demand and a technology per subsector (demands first: the technologies
        # output them), then the free supply of "Other" fuels if they are inputs
        entities = build_industry_entities(
            demand_df,
            input_split_df,
            input_fuels_of,
            cfg.provinces,
            cfg.future_periods,
            cfg.input_split_operator,
            demand_notes=_demand_notes(
                cfg.ceud_data_year,
                growth_notes(gdp_growth),
                cfg.demand_projection_point,
                cfg.other_fuels,
            ),
            split_notes=_input_split_notes(cfg.ceud_data_year),
            lifetime=cfg.period_step,
            data_id=sector_data_id,
        )
        logger.info(
            f"Building {len(entities.demands)} industry demands and technologies"
            + (
                ", and the free supply of other fuels"
                if entities.free_other_supply is not None
                else ""
            )
        )
        entities.build(db_conn)

    return CANOEModuleOutput(
        # The fuels the technologies take, where they take them ("Other" fuels are
        # supplied by the industry itself)
        fuel_imports=entities.fuel_imports()
    )


def _demand_notes(
    ceud_data_year: int,
    gdp_source: str,
    demand_projection_point: DemandProjectionPoint,
    other_fuels: OtherFuelsTreatment,
) -> str:
    point = {
        DemandProjectionPoint.PeriodEnd: "at the end of each period",
        DemandProjectionPoint.PeriodStart: "at the start of each period",
        DemandProjectionPoint.Legacy: "at the start of each period, relative to the first",
    }[demand_projection_point]
    other = {
        OtherFuelsTreatment.Deduct: ", less its 'Other' fuels,",
        OtherFuelsTreatment.Free: "",
    }[other_fuels]
    return (
        f"Energy use of the industry subsector (NRCan, {ceud_data_year}){other} "
        + f"indexed to projected gdp growth {point} ({gdp_source}). Atlantic "
        + "provinces split by their share of the subsector's energy use (StatCan, "
        + f"{2023})"
    )


def _input_split_notes(ceud_data_year: int) -> str:
    return (
        f"Shares of the subsector's energy use by source (NRCan, {ceud_data_year}), "
        + "rounded to 3 decimals; sources not published share the rest evenly, and "
        + "the shares of the sources not modelled are spread over the modelled fuels "
        + "in proportion"
    )

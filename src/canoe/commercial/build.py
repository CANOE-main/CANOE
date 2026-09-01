# pyright: reportImportCycles=false

from typing import TYPE_CHECKING

from loguru import logger

from canoe.commercial.comstock_processing import load_and_process_comstock
from canoe.commercial.existing_capacity import compute_existing_capacity
from canoe.common import CANOEFuelImport, CANOEModuleOutput, atomic_transaction

from .validation import validate_db_against_config

if TYPE_CHECKING:
    from .config import CANOECommercialConfig


def build_commercial(cfg: "CANOECommercialConfig") -> CANOEModuleOutput:
    """
    Main function of the CANOE commercial sector.
    """
    logger.info(
        f"Running COMMERCIAL (high-resolution) sector on {cfg.database_file}...\n"
    )

    # Accumulators
    fuel_imports: list[CANOEFuelImport] = []

    # Wrap everything in an atomic transaction
    with atomic_transaction(cfg.database_file) as db_conn:
        # Validate canoe-base DB structure against module config
        validate_db_against_config(cfg, db_conn)

        # Load and pre-process data sources
        # Estimated from Cosmtock
        province_dsd = load_and_process_comstock(cfg)
        existing_capacity = compute_existing_capacity(cfg)

        # Per province:
        # DSD
        # Existing Capacity
        # New Capacity
        # Emissions

    return CANOEModuleOutput(fuel_imports=fuel_imports)

    # TODO This is data pre-processing that we will come back to
    #
    # Step 1: Data is already loaded onto cfg by validate_from_toml → _load_data()
    # aeo_data = cfg.aeo_cdm
    # gdp_index = cfg.gdp_index

    # emis_factors = None
    # if cfg.include_emissions:
    #     raw_emis = data_scraper.fetch_emission_factors(
    #         url=cfg.epa_url,
    #         cache_dir=cfg.cache_dir,
    #         force_download=cfg.force_download,
    #     )
    #     emis_factors = emission_activity.prepare_emission_factors(raw_emis, cfg)

    # Step 2: Write module-specific commodity rows
    # techcom.write_commodities(cfg, db_conn)

    # # Step 3: Per-region subsector processing
    # for region in cfg.province_list:
    #     print(f"Aggregating {region}...\n")

    #     df_dsd = comstock_dsd.calculate_dsds(region, cfg)
    #     df_exs = existing_capacity.aggregate_region(
    #         region, df_dsd, aeo_data, gdp_index, cfg, db_conn
    #     )
    #     new_capacity.aggregate_region(region, df_exs, aeo_data, cfg, db_conn)

    #     if cfg.include_emissions:
    #         emission_activity.aggregate_region(region, emis_factors, cfg, db_conn)

    #     print(f"Aggregated {region}.\n")

    # # Step 4: Register data sources and datasets
    # post_processing.write_data_registry(cfg, db_conn)

    # db_conn.close()

    # if cfg.clone_to_xlsx:
    #     utils.database_converter().clone_sqlite_to_excel(
    #         from_sqlite_file=cfg.database_file,
    #         to_excel_file=cfg.excel_target_file,
    #         excel_template_file=cfg.excel_template_file,
    #     )

    # print(f"Commercial sector aggregated into {os.path.basename(cfg.database_file)}\n")

    # if cfg.show_plots:
    #     save_plots()


# def save_plots(output_dir="output_plots"):
#     os.makedirs(output_dir, exist_ok=True)
#     print("Finished and saving plots.")
#     for fig_num in pp.get_fignums():
#         fig = pp.figure(fig_num)
#         # Try suptitle first, then first axes title, then fall back to figure number
#         title = fig.get_suptitle()
#         if not title and fig.axes:
#             title = fig.axes[0].get_title()
#         filename = title if title else f"figure_{fig_num}"
#         # Sanitize filename: replace characters that are invalid in Windows filenames
#         filename = re.sub(r'[\\/:*?"<>|\x00-\x1f .,]', "_", filename)
#         filepath = os.path.join(output_dir, f"{filename}.pdf")
#         fig.savefig(filepath, bbox_inches="tight")
#         print(f"Saved {filepath}")


if __name__ == "__main__":
    # build_database()
    ...

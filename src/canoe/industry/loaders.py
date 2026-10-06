"""
Loaders for the cached datasets used only by the industry sector.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, table numbers, row labels; the layout shared by the CEUD tables
is in `canoe.common.ceud`), so when the cache changes shape the error points to the
function to fix. They return tidy frames; everything downstream is independent of
the source layout.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel, CANOEProvince, GoldConnectorConfig
from canoe.common.ceud import CEUDEnergyUse, parse_ceud_energy_use

from .subsectors import IndustrySubsector

CEUD_INDUSTRY_SOURCES: dict[str, CANOEFuel] = {
    "Electricity": CANOEFuel.Electricity,
    "Natural Gas": CANOEFuel.NaturalGas,
    "Diesel Fuel Oil, Light Fuel Oil and Kerosene": CANOEFuel.Diesel,
    "Heavy Fuel Oil": CANOEFuel.HeavyFuelOil,
    "Still Gas and Petroleum Coke": CANOEFuel.PetroleumCoke,
    "LPG and Gas Plant NGL": CANOEFuel.NaturalGasLiquids,
    "Coal": CANOEFuel.Coal,
    "Coke and Coke Oven Gas": CANOEFuel.Coke,
    "Wood Waste and Pulping Liquor": CANOEFuel.Wood,
    "Other2": CANOEFuel.Other,
}
"""Energy sources of the NRCan CEUD industry tables (row labels, "Other2" with its
footnote mark) -> CANOE fuel. Every source has a CANOE fuel."""

_CEUD_TABLES: dict[IndustrySubsector, tuple[int, str]] = {
    IndustrySubsector.Construction: (3, "Construction"),
    IndustrySubsector.PulpAndPaper: (4, "Pulp and Paper"),
    IndustrySubsector.SmeltingAndRefining: (5, "Smelting and Refining"),
    IndustrySubsector.PetroleumRefining: (6, "Petroleum Refining"),
    IndustrySubsector.Cement: (7, "Cement"),
    IndustrySubsector.Chemicals: (8, "Chemicals"),
    IndustrySubsector.IronAndSteel: (9, "Iron and Steel"),
    IndustrySubsector.OtherManufacturing: (10, "Other Manufacturing"),
    IndustrySubsector.Forestry: (11, "Forestry"),
    IndustrySubsector.Mining: (12, "Mining, Quarrying, and Oil and Gas Extraction"),
}
"""Number of each subsector's CEUD industry table and its name in the table (in the
total row, "Total <name> Energy Use (PJ)"). Table 2, energy use by industry, holds
the same totals and is not read."""


def get_ceud_industry_energy_use(
    nrcan_code: str,
    subsector: IndustrySubsector,
    data_year: int,
    cache_config: GoldConnectorConfig,
) -> CEUDEnergyUse:
    """
    Total energy use and energy use by source of an industry subsector in a NRCan
    CEUD industry table, see `canoe.common.ceud.parse_ceud_energy_use`.

    Parameters
    ----------
    nrcan_code : str
        Tables of the region, see `CANOEProvince.get_nrcan_code` (the Atlantic
        provinces share the `ATL` tables).
    subsector : IndustrySubsector
        Subsector, one table each.
    data_year : int
        Year (column) read.
    cache_config : GoldConnectorConfig
        Location and date of the cache.

    Raises
    ------
    ValueError
        If the table lacks `data_year`, an expected row, has unexpected energy
        sources or values that are neither numbers nor NRCan missing-value markers.
    """
    table, name = _CEUD_TABLES[subsector]
    dataset = f"nrcan_agg_{nrcan_code}_{table}"
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / dataset / f"{dataset}_{cache_config.cache_date}.parquet"
    logger.debug(
        f"Loading cached CEUD industry table {nrcan_code} {table} "
        + f"({subsector.get_desc_name()}, {data_year})"
    )
    return parse_ceud_energy_use(
        pd.read_parquet(file_path),
        dataset,
        data_year,
        f"Total {name} Energy Use (PJ)",
        CEUD_INDUSTRY_SOURCES,
    )


def get_statcan_atlantic_industry_shares() -> dict[
    IndustrySubsector, dict[CANOEProvince, float]
]:
    """
    Share of each Atlantic province in the energy use of each industry subsector of
    the Atlantic region, to split the CEUD Atlantic tables.

    Statistics Canada Table 25-10-0029-01, 2023, "Total primary and secondary energy"
    used by the subsector's industry, divided by its sum over the four provinces. A
    province where StatCan reports no energy use for the industry has a share of 0;
    StatCan reports none for iron and steel in any Atlantic province (nor does the
    CEUD).

    TODO: the cached `statcan_25100029` only has the commercial rows. Hard-coded from
    the previous industry module until the cache includes the industry rows; then
    read them here (see `DATA_LAKE_REQUESTS.md`).

    Examples
    --------
    >>> shares = get_statcan_atlantic_industry_shares()
    >>> {s.short_desc(): round(sum(shares[s].values()), 12) for s in shares}
    {'CON': 1.0, 'PULP': 1.0, 'SMELT': 1.0, 'REFINING': 1.0, 'CEMENT': 1.0, 'CHEM': 1.0, 'STEEL': 0.0, 'OTH_MAN': 1.0, 'FOR': 1.0, 'MINING': 1.0}
    """
    NB = CANOEProvince.NEW_BRUNSWICK
    NL = CANOEProvince.NEWFOUNDLAND_AND_LABRADOR
    NS = CANOEProvince.NOVA_SCOTIA
    PEI = CANOEProvince.PRINCE_EDWARD_ISLAND
    return {
        # "Construction"
        IndustrySubsector.Construction: {
            NB: 0.15729890764647467,
            NL: 0.5255213505461768,
            NS: 0.26097318768619665,
            PEI: 0.056206554121151935,
        },
        # "Pulp and paper manufacturing"
        IndustrySubsector.PulpAndPaper: {
            NB: 0.7438942665673864,
            NL: 0.13968726731198808,
            NS: 0.11448250186150409,
            PEI: 0.00193596425912137,
        },
        # "Aluminum and non-ferrous metal manufacturing"
        IndustrySubsector.SmeltingAndRefining: {NB: 0.0, NL: 1.0, NS: 0.0, PEI: 0.0},
        # "Refined petroleum products manufacturing"
        IndustrySubsector.PetroleumRefining: {NB: 1.0, NL: 0.0, NS: 0.0, PEI: 0.0},
        # "Cement manufacturing"
        IndustrySubsector.Cement: {NB: 0.0, NL: 0.0, NS: 1.0, PEI: 0.0},
        # "Chemicals manufacturing"
        IndustrySubsector.Chemicals: {
            NB: 0.2978986402966625,
            NL: 0.17552533992583436,
            NS: 0.25339925834363414,
            PEI: 0.273176761433869,
        },
        # " Iron and steel manufacturing" (leading space in the source)
        IndustrySubsector.IronAndSteel: {NB: 0.0, NL: 0.0, NS: 0.0, PEI: 0.0},
        # "All other manufacturing"
        IndustrySubsector.OtherManufacturing: {
            NB: 0.4046914269757051,
            NL: 0.05752583077352695,
            NS: 0.34247416922647306,
            PEI: 0.19530857302429488,
        },
        # "Forestry, logging and support activities"
        IndustrySubsector.Forestry: {
            NB: 0.27053140096618356,
            NL: 0.29200214707461086,
            NS: 0.43209876543209874,
            PEI: 0.005367686527106817,
        },
        # "Total mining and oil and gas extraction"
        IndustrySubsector.Mining: {
            NB: 0.07529435045018304,
            NL: 0.8568318986840804,
            NS: 0.06787375086573662,
            PEI: 0.0,
        },
    }

"""
Loaders for the cached datasets used only by the agriculture sector.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, row labels; the layout shared by the CEUD tables is in
`canoe.common.ceud`), so when the cache changes shape the error points to the
function to fix. They return tidy frames; everything
downstream is independent of the source layout.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel, CANOEProvince, GoldConnectorConfig
from canoe.common.ceud import CEUDEnergyUse, parse_ceud_energy_use

CEUD_AGRICULTURE_SOURCES: dict[str, CANOEFuel | None] = {
    "Electricity": CANOEFuel.Electricity,
    "Natural Gas": CANOEFuel.NaturalGas,
    "Motor Gasoline": CANOEFuel.Gasoline,
    "Diesel Fuel Oil": CANOEFuel.Diesel,
    "Light Fuel Oil": None,
    "Kerosene": None,
    "Heavy Fuel Oil": CANOEFuel.HeavyFuelOil,
    "Propane": CANOEFuel.Propane,
    "Steam": None,
}
"""Energy sources of the NRCan CEUD agriculture tables (row labels) -> CANOE fuel, or
None for sources with no CANOE fuel."""

_TOTAL_LABEL = "Total Energy Use (PJ)"
"""Row of the total energy use in the CEUD agriculture tables."""


def get_ceud_agriculture_energy_use(
    nrcan_code: str,
    data_year: int,
    cache_config: GoldConnectorConfig,
) -> CEUDEnergyUse:
    """
    Total energy use and energy use by source of an NRCan CEUD agriculture table, see
    `canoe.common.ceud.parse_ceud_energy_use`.

    Parameters
    ----------
    nrcan_code : str
        Table of the region, see `CANOEProvince.get_nrcan_code` (the Atlantic
        provinces share the `ATL` table).
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
    dataset = f"nrcan_agr_{nrcan_code}"
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / dataset / f"{dataset}_{cache_config.cache_date}.parquet"
    logger.debug(f"Loading cached CEUD agriculture table {nrcan_code} ({data_year})")
    return parse_ceud_energy_use(
        pd.read_parquet(file_path),
        dataset,
        data_year,
        _TOTAL_LABEL,
        CEUD_AGRICULTURE_SOURCES,
    )


def get_statcan_atlantic_agriculture_shares() -> dict[CANOEProvince, float]:
    """
    Share of each Atlantic province in the agriculture energy use of the Atlantic
    region, to split the CEUD Atlantic table.

    Statistics Canada Table 25-10-0029-01, 2023, "Total primary and secondary energy"
    used by "Agriculture, fishing, hunting and trapping", divided by its sum over the
    four provinces.

    TODO: the cached `statcan_25100029` only has the commercial rows. Hard-coded from
    the previous agriculture module until the cache includes the agriculture rows;
    then read them here.

    Examples
    --------
    >>> round(sum(get_statcan_atlantic_agriculture_shares().values()), 12)
    1.0
    """
    return {
        CANOEProvince.NEW_BRUNSWICK: 0.20507111935683364,
        CANOEProvince.NEWFOUNDLAND_AND_LABRADOR: 0.10723562152133581,
        CANOEProvince.NOVA_SCOTIA: 0.3559678416821274,
        CANOEProvince.PRINCE_EDWARD_ISLAND: 0.33172541743970313,
    }

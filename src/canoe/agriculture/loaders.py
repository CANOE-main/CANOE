"""
Loaders for the cached datasets used only by the agriculture sector.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, row labels, missing-value markers), so when the cache changes
shape the error points to the function to fix. They return tidy frames; everything
downstream is independent of the source layout.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel, CANOEProvince, GoldConnectorConfig

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

# Row labels of the CEUD agriculture tables
_TOTAL_LABEL = "Total Energy Use (PJ)"
_ENERGY_USE_HEADER = "Energy Use by Energy Source (PJ)"
_SHARES_HEADER = "Shares (%)"
_LABEL_COLUMN = "Unnamed: 0"
# Values NRCan publishes instead of a number (not available, confidential, nil)
_MISSING_MARKERS = {"n.a.", "X", "x", "..", "–", "-"}


@dataclass(frozen=True)
class CEUDAgricultureEnergyUse:
    """
    Energy use of one NRCan CEUD agriculture table in one year.

    Parameters
    ----------
    total : float
        Total energy use (PJ), all sources.
    by_source : pd.DataFrame
        One row per energy source (index: NRCan label) with columns `fuel`
        (`CANOEFuel`, missing for sources with no CANOE fuel), `energy_use` (PJ) and
        `share` (percent of the total, as published). Values NRCan does not publish
        are NaN.
    """

    total: float
    by_source: pd.DataFrame


def get_ceud_agriculture_energy_use(
    nrcan_code: str,
    data_year: int,
    cache_config: GoldConnectorConfig,
) -> CEUDAgricultureEnergyUse:
    """
    Total energy use and energy use by source of an NRCan CEUD agriculture table.

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
    df = pd.read_parquet(file_path)

    year_column = str(data_year)
    if year_column not in df.columns:
        years = [c for c in df.columns if c.isdigit()]
        raise ValueError(
            f"{dataset}: year {data_year} not in the table. Years: {years}"
        )
    labels = [str(label).strip() for label in df[_LABEL_COLUMN]]
    values = df[year_column].tolist()

    def value(row: int) -> float:
        raw = values[row]
        if raw is None or str(raw).strip() in _MISSING_MARKERS:
            return np.nan
        try:
            return float(raw)
        except ValueError:
            raise ValueError(
                f"{dataset}: unexpected value {raw!r} in row {labels[row]!r}, {data_year}"
            ) from None

    def block(header: str, start: int) -> dict[str, int]:
        """Rows (label -> position) after the first `header` at or after `start`"""
        if header not in labels[start:]:
            raise ValueError(f"{dataset}: row {header!r} not found")
        first = labels.index(header, start) + 1
        rows: dict[str, int] = {}
        for position in range(first, len(labels)):
            if labels[position] not in CEUD_AGRICULTURE_SOURCES:
                break
            rows[labels[position]] = position
        missing = set(CEUD_AGRICULTURE_SOURCES) - set(rows)
        if missing:
            raise ValueError(
                f"{dataset}: energy sources {sorted(missing)} missing under {header!r}"
            )
        return rows

    if _TOTAL_LABEL not in labels:
        raise ValueError(f"{dataset}: row {_TOTAL_LABEL!r} not found")
    energy_use_rows = block(_ENERGY_USE_HEADER, 0)
    share_rows = block(_SHARES_HEADER, max(energy_use_rows.values()))

    by_source = pd.DataFrame(
        {
            "fuel": list(CEUD_AGRICULTURE_SOURCES.values()),
            "energy_use": [value(energy_use_rows[s]) for s in CEUD_AGRICULTURE_SOURCES],
            "share": [value(share_rows[s]) for s in CEUD_AGRICULTURE_SOURCES],
        },
        index=pd.Index(list(CEUD_AGRICULTURE_SOURCES), name="source"),
    )
    return CEUDAgricultureEnergyUse(
        total=value(labels.index(_TOTAL_LABEL)), by_source=by_source
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

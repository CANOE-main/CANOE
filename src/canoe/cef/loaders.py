"""
Loaders of the data lake cache used by the CEF module.

One function per cached dataset; each is the only place that knows the file path, the
column names and the labels of the source, and returns a tidy frame in CANOE terms.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel, CANOEProvince, CANOESector, GoldConnectorConfig


def cef_fuels(sector: CANOESector) -> dict[str, CANOEFuel | None]:
    """
    CANOE fuel of each energy source ("Variable") of the CEF end-use demand tables of
    `sector`, `None` for the sources left out.

    Sources left out: the totals ("Total End-Use"), "Other" (no fuel to supply it
    with) and transportation "Lubricants" (not burned). Refined petroleum products
    ("RPP") are oil in buildings and heavy fuel oil in industry, and transportation
    LPG is propane, as EIA prices propane and not LPG. Each sector reports one biofuel
    source ("Biofuels & Emerging Energy", or "Biofuels" in transportation).

    Examples
    --------
    >>> cef_fuels(CANOESector.Industry)["RPP"]
    HeavyFuelOil
    >>> cef_fuels(CANOESector.Transportation)["LPG"]
    Propane
    """
    if sector == CANOESector.Transportation:
        return {
            "Aviation Fuel": CANOEFuel.JetFuel,
            "Biofuels": CANOEFuel.BioEnergy,
            "Diesel": CANOEFuel.Diesel,
            "Electricity": CANOEFuel.Electricity,
            "Heavy Fuel Oil": CANOEFuel.HeavyFuelOil,
            "Hydrogen": CANOEFuel.Hydrogen,
            "LPG": CANOEFuel.Propane,
            "Lubricants": None,
            "Motor Gasoline": CANOEFuel.Gasoline,
            "Natural Gas": CANOEFuel.NaturalGas,
            "Total End-Use": None,
        }
    return {
        "Biofuels & Emerging Energy": CANOEFuel.BioEnergy,
        "Electricity": CANOEFuel.Electricity,
        "Hydrogen": CANOEFuel.Hydrogen,
        "Natural Gas": CANOEFuel.NaturalGas,
        "Other": None,
        "RPP": CANOEFuel.HeavyFuelOil
        if sector == CANOESector.Industry
        else CANOEFuel.Oil,
        "Total End-Use": None,
    }


def get_cef_end_use_demand(
    cache_config: GoldConnectorConfig, scenario: str, sector: CANOESector
) -> pd.DataFrame:
    """
    Projected end-use energy demand of `sector` by province and fuel, CER Canada's
    Energy Future 2023 (cached table `cef`).

    Parameters
    ----------
    cache_config : GoldConnectorConfig
        Location and date of the cache.
    scenario : str
        CER scenario, as named in the data (see
        `canoe.common.projections.CERScenario`).
    sector : CANOESector
        End-use sector, see `CANOESector.get_cef_sector`.

    Returns
    -------
    pd.DataFrame
        Columns `region` (`CANOEProvince`), `year`, `fuel` (`CANOEFuel`) and `value`
        (PJ), one row per province, year and fuel of `cef_fuels`. Territories and
        the national total are left out.

    Raises
    ------
    ValueError
        If the scenario or sector has no rows, or the sector reports a source missing
        from `cef_fuels`.
    """
    sector_name = sector.get_cef_sector()
    if sector_name is None:
        raise ValueError(f"CEF end-use demand: no {sector} sector in the CEF tables")

    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / "cef" / f"cef_{cache_config.cache_date}.parquet"
    logger.debug(f"Loading cached CEF end-use demand, {scenario}, {sector_name}")
    df = pd.read_parquet(file_path)

    rows = df.loc[(df["Scenario"] == scenario) & (df["Sector"] == sector_name)]
    if rows.empty:
        raise ValueError(
            f"CEF end-use demand: no rows for scenario {scenario!r} and sector "
            + f"{sector_name!r}; scenarios: {sorted(df['Scenario'].unique())}, "
            + f"sectors: {sorted(df['Sector'].unique())}"
        )

    fuels = cef_fuels(sector)
    unknown = sorted(set(rows["Variable"]) - set(fuels))
    if unknown:
        raise ValueError(
            f"CEF end-use demand: unknown energy sources {unknown} in {sector_name}"
        )

    # The provinces; "Canada" and the territories are not CANOE regions
    rows = rows.loc[rows["Region"].isin([p.value for p in CANOEProvince])]
    rows = rows.loc[rows["Variable"].map(fuels).notna()]
    return pd.DataFrame(
        {
            "region": rows["Region"].map(CANOEProvince.from_str),
            "year": rows["Year"].astype(int),
            "fuel": rows["Variable"].map(fuels),
            "value": rows["Value"].astype(float),
        }
    ).reset_index(drop=True)

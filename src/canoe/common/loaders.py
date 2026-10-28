"""
Loaders for cached datasets used by more than one sector.

Each function reads a single dataset of the data lake cache and is the only place that
knows its path and layout, so when the cache changes shape the error points to the
function to fix. Sector-specific datasets have their own loaders in each sector.
"""

from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common.cache_connector import GoldConnectorConfig
from canoe.common.emissions import CANOEEmission
from canoe.common.fuels import CANOEFuel
from canoe.common.provinces import CANOEProvince
from canoe.common.sectors import CANOESector


def get_cer_gdp(cache_config: GoldConnectorConfig, scenario: str) -> pd.DataFrame:
    """
    Projected real GDP of Canada (CER Canada's Energy Future 2023 macro indicators).

    Parameters
    ----------
    cache_config : GoldConnectorConfig
        Location and date of the cache.
    scenario : str
        CER scenario, as named in the data (see
        `canoe.common.projections.CERScenario`).

    Returns
    -------
    pd.DataFrame
        Columns `year` and `gdp` (2012 $ millions).

    Raises
    ------
    ValueError
        If the scenario has no GDP in the data.
    """
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_folder = cache_path / "cer_macro"
    file_path = file_folder / f"cer_macro_{cache_config.cache_date}.parquet"
    logger.debug(f"Loading cached CER GDP projections, scenario {scenario}")
    df = pd.read_parquet(file_path)
    rows = df.loc[
        (df["Scenario"] == scenario)
        & (df["Variable"] == "Real Gross Domestic Product ($2012 Millions)")
    ]
    if rows.empty:
        raise ValueError(
            f"CER macro indicators: no real GDP for scenario {scenario!r}; scenarios: "
            + f"{sorted(df['Scenario'].unique())}"
        )
    return pd.DataFrame(
        {"year": rows["Year"].astype(int), "gdp": rows["Value"].astype(float)}
    ).reset_index(drop=True)


def get_statcan_population_estimates() -> pd.DataFrame:
    """
    Population on January 1st of each year, by geography (Canada, provinces and
    territories), StatCan Table 17-10-0009-01 (quarterly estimates), as the previous
    residential module cached it.

    TODO: read from `canoe/common/data` until the data lake has the table (see
    `DATA_LAKE_REQUESTS.md`).

    Returns columns `geo` (StatCan name, e.g. "Ontario"), `year` and `population`.
    """
    resource = files("canoe.common").joinpath("data/statcan_17100009.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    # Quarterly estimates ("1946-01", "1946-04", ...): keep the January ones
    january = df.loc[df["REF_DATE"].str.endswith("-01") & df["VALUE"].notna()]
    return pd.DataFrame(
        {
            "geo": january["GEO"],
            "year": january["REF_DATE"].str.removesuffix("-01").astype(int),
            "population": january["VALUE"].astype(float),
        }
    ).reset_index(drop=True)


def get_statcan_population_projections() -> pd.DataFrame:
    """
    Projected population (July 1st) by geography, medium-growth scenario M1, all
    genders and ages, StatCan Table 17-10-0057-01.

    Reads `data/statcan_17100057_extract.csv`, the rows of the full table this
    function keeps (the full file is 154 MB, see `make_statcan_17100057_extract.py`);
    it filters as if it read the full table.

    TODO: read from `canoe/common/data` until the data lake has the table (see
    `DATA_LAKE_REQUESTS.md`).

    Returns columns `geo`, `year` and `population` (persons).
    """
    resource = files("canoe.common").joinpath("data/statcan_17100057_extract.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    rows = df.loc[
        (df["Projection scenario"] == "Projection scenario M1: medium-growth")
        & (df["Gender"] == "Total - gender")
        & (df["Age group"] == "All ages")
        & df["VALUE"].notna()
    ]
    return pd.DataFrame(
        {
            "geo": rows["GEO"],
            "year": rows["REF_DATE"].astype(int),
            # Published in thousands
            "population": rows["VALUE"].astype(float) * 1000,
        }
    ).reset_index(drop=True)


def get_exchange_and_inflation_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Exchange rates and Canadian inflation by year, to convert costs to CAD of the
    model currency year.

    TODO: not in the cache yet; read from `canoe/common/data` until it is (see
    `DATA_LAKE_REQUESTS.md`).

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        - Exchange rates by year (index), CAD per unit of each currency (columns
          `CAD`, `USD`, `EUR`, `GBP`, `AUD`).
        - Price indices by year (index), 1 in 2020 (columns `gdp_deflator`,
          `general_cpi`, ...).
    """
    exchange_resource = files("canoe.common").joinpath("data/currency_exchange.csv")
    with exchange_resource.open("rb") as f:
        exchange_df = pd.read_csv(f, index_col=0)

    inflation_resource = files("canoe.common").joinpath("data/cad_inflation.csv")
    with inflation_resource.open("rb") as f:
        inflation_df = pd.read_csv(f, index_col=0)
    return exchange_df, inflation_df


def get_usca_weather_map(
    cache_config: GoldConnectorConfig, province: CANOEProvince
) -> np.ndarray:
    """
    Weather map from the US state of a province's profiles to the province (cached as
    `weather_maps_<province>`): an 8760 x 8760 matrix whose row h averages the hours
    of the US year with the temperature and humidity of hour h in the province, as
    stored (see `canoe.common.weather_maps.load_weather_maps` for the time zone).
    """
    cache_path = (
        cache_config.cache_dir
        / Path("silver")
        / cache_config.cache_date
        / Path(f"weather_maps_{province.short()}")
        / Path(f"weather_maps_{province.short()}_{cache_config.cache_date}.npz")
    )
    logger.debug(f"Loading cached weather map for {province}")
    return np.load(cache_path)["arr_0"]


def get_combustion_emission_factors() -> pd.DataFrame:
    """
    Emissions of burning each fuel in each sector (ECCC emission factors, Nova Scotia
    QRV standards, GREET), as in the previous fuel module. Used by the fuel module
    (combustion emissions) and the electricity module (carbon capture).

    TODO: read from the previous module's `direct_comb_emission.csv` (copied to
    `canoe/common/data`) until the data lake has the factors (see
    `DATA_LAKE_REQUESTS.md`). The factors are national: provincial ones (e.g. coal by
    type) are not represented.

    Returns
    -------
    pd.DataFrame
        Columns `sector` (`CANOESector`), `fuel` (`CANOEFuel`), `emission`
        (`CANOEEmission`), `factor` (kt per PJ of fuel), `notes`, `reference`.
    """
    file_name = "combustion_emission_factors.csv"
    resource = files("canoe.common").joinpath(f"data/{file_name}")
    with resource.open("rb") as f:
        factors = parse_previous_emission_factors(
            pd.read_csv(f, encoding="utf-8-sig"), file_name
        )
    tags_and_codes = factors["commodity"].str.split("_", n=1, expand=True)
    sectors = tags_and_codes[0].map(CANOESector)
    if sectors.isna().any():
        raise ValueError(
            f"{file_name}: unknown sector tags "
            + f"{sorted(set(tags_and_codes.loc[sectors.isna(), 0]))}"
        )
    return factors.assign(
        sector=sectors,
        fuel=[previous_fuel(code, file_name) for code in tags_and_codes[1]],
    ).loc[:, ["sector", "fuel", "emission", "factor", "notes", "reference"]]


def parse_previous_emission_factors(raw: pd.DataFrame, file_name: str) -> pd.DataFrame:
    """
    Emission factors in the layout of the previous fuel module (`commodity`,
    `emission`, `value`, `units`, `notes`, `source`), as `commodity`, `emission`
    (`CANOEEmission`), `factor` (kt/PJ), `notes`, `reference`. CO2e rows are
    dropped: the central emissions step derives CO2-equivalents.
    """
    EMISSIONS = {
        "co2": CANOEEmission.CO2,
        "ch4": CANOEEmission.CH4,
        "n2o": CANOEEmission.N2O,
    }
    TO_KT_PER_PJ = {"kTonne/PJ": 1.0, "Tonne/PJ": 1e-3}
    REFERENCES = {
        "F4": "Government of Canada, Emission factors and reference values",
        "F6": "Nova Scotia Department of Environment and Climate Change, QRV "
        + "standards",
        "F7": "Environment and Climate Change Canada (2024), Fuel life cycle "
        + "assessment model",
        "F8": "Argonne National Laboratory, GREET model",
    }
    raw = raw.loc[raw["emission"] != "co2e"]
    unknown_units = set(raw["units"]) - set(TO_KT_PER_PJ)
    unknown_emissions = set(raw["emission"]) - set(EMISSIONS)
    if unknown_units or unknown_emissions:
        raise ValueError(
            f"{file_name}: unknown units {sorted(unknown_units)} or emissions "
            + f"{sorted(unknown_emissions)}"
        )
    # Some rows have no source code; their reference is left empty
    return pd.DataFrame(
        {
            "commodity": raw["commodity"],
            "emission": [EMISSIONS[e] for e in raw["emission"]],
            "factor": raw["value"].astype(float)
            * [TO_KT_PER_PJ[u] for u in raw["units"]],
            "notes": raw["notes"].fillna("").str.strip(),
            "reference": [REFERENCES.get(s, "") for s in raw["source"]],
        }
    ).reset_index(drop=True)


def previous_fuel(code: str, file_name: str) -> CANOEFuel:
    """
    The fuel of a fuel code of the previous fuel module's commodity names
    (`<S>_<fuel>`, `F_<fuel>`).

    Examples
    --------
    >>> previous_fuel("bio_m", "file.csv")
    SolidBioenergy
    """
    FUEL_CODES = {
        "bio": CANOEFuel.BioEnergy,
        "bio_g": CANOEFuel.GaseousBioenergy,
        "bio_m": CANOEFuel.SolidBioenergy,
        "cng": CANOEFuel.CompressedNaturalGas,
        "coal": CANOEFuel.Coal,
        "coke": CANOEFuel.Coke,
        "dsl": CANOEFuel.Diesel,
        "eth": CANOEFuel.Ethanol,
        "gsl": CANOEFuel.Gasoline,
        "hfo": CANOEFuel.HeavyFuelOil,
        "jtf": CANOEFuel.JetFuel,
        "lng": CANOEFuel.LiquifiedNaturalGas,
        "lpg": CANOEFuel.LiquifiedPretroleumGas,
        "mdo": CANOEFuel.MarineDieselOil,
        "ng": CANOEFuel.NaturalGas,
        "ngl": CANOEFuel.NaturalGasLiquids,
        "oil": CANOEFuel.Oil,
        "pcoke": CANOEFuel.PetroleumCoke,
        "prop": CANOEFuel.Propane,
        "rdsl": CANOEFuel.RenewableDiesel,
        "spk": CANOEFuel.SyntheticJetFuel,
        "wood": CANOEFuel.Wood,
    }
    if code not in FUEL_CODES:
        raise ValueError(f"{file_name}: unknown fuel code {code!r}")
    return FUEL_CODES[code]

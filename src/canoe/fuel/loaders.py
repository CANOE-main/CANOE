"""
Loaders for the datasets used only by the fuel module.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, labels, units), so when the cache changes shape the error points
to the function to fix. They return tidy frames in CANOE terms; everything downstream
is independent of the source layout. Sources not in the cache yet are read from
`canoe/fuel/data` or hard-coded, with a TODO (see `DATA_LAKE_REQUESTS.md`).
"""

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pandas as pd
from loguru import logger

from canoe.common import CANOEEmission, CANOEFuel, CANOESector, GoldConnectorConfig


@dataclass(frozen=True)
class SourcePrices:
    """
    Fuel prices of one source, in `currency` of `currency_year` per `units`.

    Parameters
    ----------
    prices : pd.DataFrame
        One row per price, the columns of each loader plus `price`.
    currency : str
        Currency of the prices (a column of the exchange table, e.g. `USD`).
    currency_year : int
        Year of the currency (real dollars of that year).
    units : str
        Energy unit the prices are per, e.g. `$/MMBtu`.
    reference : str
        The source, for notes.
    """

    prices: pd.DataFrame
    currency: str
    currency_year: int
    units: str
    reference: str


def _cache_dir(cache_config: GoldConnectorConfig) -> Path:
    return cache_config.cache_dir / Path("silver") / cache_config.cache_date


def get_eia_energy_prices(cache_config: GoldConnectorConfig) -> SourcePrices:
    """
    Projected delivered energy prices by sector and fuel, US average (EIA Annual
    Energy Outlook 2025, Table 3 'Energy Prices by Sector and Source', reference
    case).

    Only the real prices of each sector; the averages over all sectors are left out.
    Sectors and fuels keep the EIA labels, see `CANOESector.get_eia_sector` and
    `CANOEFuel.get_eia_fuel`.

    Returns
    -------
    SourcePrices
        Columns `eia_sector`, `eia_fuel`, `year`, `price`, in 2024 USD per MMBtu.

    Raises
    ------
    ValueError
        If the table has no real prices in the expected unit or a price is not a
        number.
    """
    # EIA AEO Table 3: real prices are "Energy Prices : <sector> : <fuel>" in this unit
    _EIA_REAL_UNIT = "2024 $/MMBtu"
    _EIA_CURRENCY_YEAR = 2024
    _EIA_ALL_SECTORS = "Average Price to All Users"

    file_path = (
        _cache_dir(cache_config)
        / "eia_table3"
        / f"eia_table3_{cache_config.cache_date}.parquet"
    )
    logger.debug(f"Loading cached EIA AEO Table 3 energy prices from {file_path}")
    df = pd.read_parquet(file_path)

    real = df.loc[df["unit"] == _EIA_REAL_UNIT, ["seriesName", "period", "value"]]
    if real.empty:
        raise ValueError(
            f"EIA AEO Table 3: no prices in '{_EIA_REAL_UNIT}'. Units in the table: "
            + f"{sorted(df['unit'].unique())}"
        )
    series_names = pd.Series(real["seriesName"], dtype=str)
    labels = series_names.str.split(" : ", expand=True)
    if labels.shape[1] != 3 or bool((labels[0] != "Energy Prices").any()):
        raise ValueError(
            "EIA AEO Table 3: expected series 'Energy Prices : <sector> : <fuel>' in "
            + f"'{_EIA_REAL_UNIT}', got e.g. {series_names.iloc[0]!r}"
        )
    price = pd.Series(pd.to_numeric(real["value"], errors="coerce"))
    if bool(price.isna().any()):
        raise ValueError(
            f"EIA AEO Table 3: prices that are not numbers:\n{real[price.isna()]}"
        )
    prices = pd.DataFrame(
        {
            "eia_sector": labels[1],
            "eia_fuel": labels[2],
            "year": pd.Series(pd.to_numeric(real["period"], errors="raise")).astype(
                int
            ),
            "price": price,
        }
    )
    prices = prices.loc[prices["eia_sector"] != _EIA_ALL_SECTORS].reset_index(drop=True)
    return SourcePrices(
        prices=prices,
        currency="USD",
        currency_year=_EIA_CURRENCY_YEAR,
        units="$/MMBtu",
        reference="EIA Annual Energy Outlook 2025, Table 3 (US average)",
    )


def get_atb_fuel_prices(cache_config: GoldConnectorConfig) -> SourcePrices:
    """
    Fuel price of the NREL ATB technologies whose fuel CANOE uses (see
    `CANOEFuel.get_atb_technology`): fuel cost divided by heat rate of the default
    plant (moderate scenario, market case).

    The ATB fuel costs are constant over the years; the price is a single value per
    technology.

    Returns
    -------
    SourcePrices
        Columns `atb_technology`, `price`, in 2022 USD per MMBtu.

    Raises
    ------
    ValueError
        If a technology is missing, has no single default plant or its price
        changes over the years.
    """
    # NREL ATB 2024: fuel cost ($/MWh of electricity) and heat rate (MMBtu/MWh) of the
    # default plant of each technology, in 2022 dollars
    _ATB_CURRENCY_YEAR = 2022
    _ATB_FILTERS = {
        "scenario": "Moderate",
        "core_metric_case": "Market",
        "crpyears": "30",
    }

    file_path = (
        _cache_dir(cache_config) / "atb" / f"atb_{cache_config.cache_date}.parquet"
    )
    logger.debug(f"Loading cached NREL ATB fuel costs from {file_path}")
    df = pd.read_parquet(file_path)

    technologies = sorted(
        {
            technology
            for fuel in CANOEFuel
            if (technology := fuel.get_atb_technology()) is not None
        }
    )
    mask = (
        df["technology"].isin(technologies)
        & df["core_metric_parameter"].isin(["Fuel", "Heat Rate"])
        & (df["default"] == "1")
    )
    for column, value in _ATB_FILTERS.items():
        mask &= df[column] == value
    selected = df.loc[
        mask, ["technology", "core_metric_parameter", "core_metric_variable", "value"]
    ]

    rows: list[dict[str, str | float]] = []
    for technology in technologies:
        # One fuel cost and heat rate per year; pivot fails on duplicates
        values = (
            selected.loc[selected["technology"] == technology]
            .pivot(
                index="core_metric_variable",
                columns="core_metric_parameter",
                values="value",
            )
            .astype(float)
        )
        if values.empty or {"Fuel", "Heat Rate"} - set(values.columns):
            raise ValueError(
                f"NREL ATB: no fuel cost and heat rate for the default {technology} "
                + f"plant ({_ATB_FILTERS})"
            )
        price_by_year = (values["Fuel"] / values["Heat Rate"]).dropna()
        if price_by_year.nunique() != 1:
            raise ValueError(
                f"NREL ATB: the {technology} fuel price changes over the years, "
                + f"expected a constant:\n{price_by_year}"
            )
        rows.append({"atb_technology": technology, "price": price_by_year.iloc[0]})

    return SourcePrices(
        prices=pd.DataFrame(rows),
        currency="USD",
        currency_year=_ATB_CURRENCY_YEAR,
        units="$/MMBtu",
        reference="NREL Annual Technology Baseline 2024",
    )


def get_fixed_fuel_prices() -> SourcePrices:
    """
    Fixed prices of the fuels priced from reports, constant over the periods:

    - Ethanol and renewable diesel (50% biodiesel, 50% HDRD): Wolinetz & Harrison,
      *Biofuels in Canada 2023* (Navius Research), average of 2012-2022 including
      transport costs in Ontario.
    - Synthetic jet fuel (SPK/HRJ pathway): NREL ATB.

    TODO: hard-coded from the previous fuel module until the data lake has the
    reports (see `DATA_LAKE_REQUESTS.md`).

    Returns
    -------
    SourcePrices
        Columns `fuel` (`CANOEFuel`), `price`, in 2020 CAD per GJ (M$/PJ).
    """
    return SourcePrices(
        prices=pd.DataFrame(
            {
                "fuel": [
                    CANOEFuel.Ethanol,
                    CANOEFuel.RenewableDiesel,
                    CANOEFuel.SyntheticJetFuel,
                ],
                "price": [25.801332399, 34.286607549, 53.947379869],
            }
        ),
        currency="CAD",
        currency_year=2020,
        units="$/GJ",
        reference="Wolinetz & Harrison (2023), Biofuels in Canada 2023 (ethanol, "
        + "renewable diesel); NREL ATB (SPK)",
    )


# Fuel codes of the previous fuel module's commodity names (`<S>_<fuel>`, `F_<fuel>`)
_PREVIOUS_FUEL_CODES: dict[str, CANOEFuel] = {
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
_EMISSIONS: dict[str, CANOEEmission] = {
    "co2": CANOEEmission.CO2,
    "ch4": CANOEEmission.CH4,
    "n2o": CANOEEmission.N2O,
}
# Units of the files and the factor to kt/PJ. CO2e rows are dropped: the central
# emissions step derives CO2-equivalents
_TO_KT_PER_PJ: dict[str, float] = {"kTonne/PJ": 1.0, "Tonne/PJ": 1e-3}
# Source codes of the files
_REFERENCES: dict[str, str] = {
    "F4": "Government of Canada, Emission factors and reference values",
    "F6": "Nova Scotia Department of Environment and Climate Change, QRV standards",
    "F7": "Environment and Climate Change Canada (2024), Fuel life cycle assessment model",
    "F8": "Argonne National Laboratory, GREET model",
}


def _read_previous_emission_factors(file_name: str) -> pd.DataFrame:
    """
    Emission factors in the layout of the previous fuel module: `commodity`,
    `emission`, `value`, `units`, `notes`, `source`. Returns `commodity`, `emission`
    (`CANOEEmission`), `factor` (kt/PJ), `notes`, `reference`, without CO2e rows.
    """
    resource = files("canoe.fuel").joinpath(f"data/{file_name}")
    with resource.open("rb") as f:
        raw = pd.read_csv(f, encoding="utf-8-sig")

    raw = raw.loc[raw["emission"] != "co2e"]
    unknown_units = set(raw["units"]) - set(_TO_KT_PER_PJ)
    unknown_emissions = set(raw["emission"]) - set(_EMISSIONS)
    if unknown_units or unknown_emissions:
        raise ValueError(
            f"{file_name}: unknown units {sorted(unknown_units)} or emissions "
            + f"{sorted(unknown_emissions)}"
        )
    # Some rows have no source code; their reference is left empty
    return pd.DataFrame(
        {
            "commodity": raw["commodity"],
            "emission": raw["emission"].map(_EMISSIONS),
            "factor": raw["value"].astype(float) * raw["units"].map(_TO_KT_PER_PJ),
            "notes": raw["notes"].fillna("").str.strip(),
            "reference": raw["source"].map(_REFERENCES).fillna(""),
        }
    ).reset_index(drop=True)


def _previous_fuel(code: str, file_name: str) -> CANOEFuel:
    if code not in _PREVIOUS_FUEL_CODES:
        raise ValueError(f"{file_name}: unknown fuel code {code!r}")
    return _PREVIOUS_FUEL_CODES[code]


def get_combustion_emission_factors() -> pd.DataFrame:
    """
    Emissions of burning each fuel in each sector (ECCC emission factors, Nova Scotia
    QRV standards, GREET), as in the previous fuel module.

    TODO: read from the previous module's `direct_comb_emission.csv` (copied to
    `canoe/fuel/data`) until the data lake has the factors (see
    `DATA_LAKE_REQUESTS.md`).

    Returns
    -------
    pd.DataFrame
        Columns `sector` (`CANOESector`), `fuel` (`CANOEFuel`), `emission`
        (`CANOEEmission`), `factor` (kt per PJ of fuel), `notes`, `reference`.
    """
    file_name = "combustion_emission_factors.csv"
    factors = _read_previous_emission_factors(file_name)
    tags_and_codes = factors["commodity"].str.split("_", n=1, expand=True)
    sectors = tags_and_codes[0].map(CANOESector)
    if sectors.isna().any():
        raise ValueError(
            f"{file_name}: unknown sector tags "
            + f"{sorted(set(tags_and_codes.loc[sectors.isna(), 0]))}"
        )
    return factors.assign(
        sector=sectors,
        fuel=[_previous_fuel(code, file_name) for code in tags_and_codes[1]],
    ).loc[:, ["sector", "fuel", "emission", "factor", "notes", "reference"]]


def get_upstream_emission_factors() -> pd.DataFrame:
    """
    Emissions of producing and delivering each fuel, before it is burned (ECCC Fuel
    LCA model, GREET), as in the previous fuel module.

    TODO: read from the previous module's `upstream_emissions_fuels.csv` (copied to
    `canoe/fuel/data`) until the data lake has the factors (see
    `DATA_LAKE_REQUESTS.md`).

    Returns
    -------
    pd.DataFrame
        Columns `fuel` (`CANOEFuel`), `emission` (`CANOEEmission`), `factor` (kt per
        PJ of fuel), `notes`, `reference`.
    """
    file_name = "upstream_emission_factors.csv"
    factors = _read_previous_emission_factors(file_name)
    if not factors["commodity"].str.startswith("F_").all():
        raise ValueError(f"{file_name}: expected F_<fuel> commodities")
    return factors.assign(
        fuel=[
            _previous_fuel(code, file_name)
            for code in factors["commodity"].str.removeprefix("F_")
        ]
    ).loc[:, ["fuel", "emission", "factor", "notes", "reference"]]

"""
Fuel price sources: from each configured source to the delivered prices the rest of
the module uses.

Every source gives a **price table**, the format a user's price file must have (see
`read_price_table`): one row per price with columns

- `region` (`CANOEProvince`), `sector` (`CANOESector`), `fuel` (`CANOEFuel`), `year`:
  what the price applies to. An empty region or year (`None`) means every province
  or every year read.
- `price`, in `currency` of `currency_year` per `units` (e.g. `USD`, 2024,
  `$/MMBtu`), row by row.
- `source`: description, for notes.

Each source then goes through the same steps (see `canoe.fuel.build`):

1. `get_price_table`: the table of the source, with its proxies (e.g. agriculture
   takes the industrial natural gas series of the EIA). Checked by
   `check_price_table`.
2. `expand_price_table`: the empty regions and years made explicit.
3. `convert_to_model_units`: the prices in M$/PJ (= $/GJ) of CAD of the model
   currency year.

`combine_price_sources` merges the tables of the sources in priority order. The
prices are delivered prices, used as they are for the import and distribution
costs (see `canoe.fuel.prices`).
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from canoe.common import CANOEFuel, CANOEProvince, CANOESector, GoldConnectorConfig
from canoe.common.currency import currency_conversion_factor
from canoe.fuel.loaders import (
    SourcePrices,
    get_atb_fuel_prices,
    get_eia_energy_prices,
    get_fixed_fuel_prices,
)


class EIAPriceSource(BaseModel):
    """EIA Annual Energy Outlook, Table 3: delivered prices by sector and fuel (US
    average, projected), with proxies for the series it lacks. Fossil fuels and
    hydrogen."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["eia"] = "eia"


class ATBPriceSource(BaseModel):
    """NREL ATB: fuel cost of the biopower and nuclear plants, constant. Bioenergy,
    wood and uranium."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["atb"] = "atb"


class FixedPriceSource(BaseModel):
    """Fixed report prices, constant. Ethanol, renewable diesel and synthetic jet
    fuel."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["fixed"] = "fixed"


class CSVPriceSource(BaseModel):
    """A price file in the format of `read_price_table`."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["csv"] = "csv"
    path: Path
    """CSV file of prices, relative to the directory the pipeline runs from."""


PriceSource = Annotated[
    EIAPriceSource | ATBPriceSource | FixedPriceSource | CSVPriceSource,
    Field(discriminator="source"),
]


class PriceFallback(StrEnum):
    """How the sources configured, in priority order, share the prices."""

    PerFuel = "per_fuel"
    """Each fuel takes all its prices (every region and sector) from the first source
    that prices it, so the prices of a fuel never mix sources."""

    PerSeries = "per_series"
    """Each (region, sector, fuel) takes its prices from the first source that has
    it, so a source fills the gaps of the ones before it."""


def _price_table(rows: list[dict[str, object]]) -> pd.DataFrame:
    """A price table of `rows`, with `year` as nullable integers."""
    table = pd.DataFrame(
        rows,
        columns=[
            "region",
            "sector",
            "fuel",
            "year",
            "price",
            "currency",
            "currency_year",
            "units",
            "source",
        ],
    )
    return table.assign(year=table["year"].astype("Int64"))


def get_price_table(
    source: PriceSource,
    cache_config: GoldConnectorConfig,
    reproduce_previous_price_errors: bool,
) -> pd.DataFrame:
    """
    The price table of `source` (see the module docstring), checked by
    `check_price_table`.

    Raises
    ------
    ValueError
        If the source's data is missing or not in the expected format.
    """
    match source:
        case EIAPriceSource():
            table = eia_price_table(
                get_eia_energy_prices(cache_config), reproduce_previous_price_errors
            )
            name = "EIA prices"
        case ATBPriceSource():
            table = atb_price_table(get_atb_fuel_prices(cache_config))
            name = "ATB prices"
        case FixedPriceSource():
            table = fixed_price_table(get_fixed_fuel_prices())
            name = "Fixed prices"
        case CSVPriceSource(path=path):
            table = read_price_table(path)
            name = str(path)
    check_price_table(table, name)
    return table


@dataclass(frozen=True)
class EIASeries:
    """
    An EIA AEO Table 3 'Energy Prices' series, named by the CANOE sector and fuel it
    is read for (see `CANOESector.get_eia_sector` and `CANOEFuel.get_eia_fuel`).
    """

    sector: CANOESector
    fuel: CANOEFuel
    factor: float = 1.0
    """Multiplier on the series, for fuels priced as a fraction of another."""


def eia_price_series(
    reproduce_previous_price_errors: bool,
) -> dict[tuple[CANOESector, CANOEFuel], EIASeries]:
    """
    EIA series each (sector, fuel) priced by the EIA is read from, reproducing the
    previous fuel module (its `fuel_list.csv` rows and `_calc_cost` proxies). See
    `FUEL_MODULE_BUGS.md` for the quirks kept (proxy series, the 0.89 and 0.9
    factors).

    With `reproduce_previous_price_errors`, residential LPG takes the transportation
    propane series: the previous module compared the output commodity with the
    technology name, so it never matched the residential one.

    Examples
    --------
    >>> key = (CANOESector.Residential, CANOEFuel.LiquifiedPretroleumGas)
    >>> eia_price_series(False)[key]
    EIASeries(sector=<CANOESector.Residential: 'RES'>, fuel=Propane, factor=1.0)
    >>> eia_price_series(True)[key]
    EIASeries(sector=<CANOESector.Transportation: 'TRP'>, fuel=Propane, factor=1.0)
    """
    S, F = CANOESector, CANOEFuel
    residential_lpg = (
        EIASeries(S.Transportation, F.Propane)
        if reproduce_previous_price_errors
        else EIASeries(S.Residential, F.Propane)
    )
    return {
        # Electricity
        (S.Electricity, F.NaturalGas): EIASeries(S.Electricity, F.NaturalGas),
        (S.Electricity, F.Coal): EIASeries(S.Industry, F.Coal),
        (S.Electricity, F.Oil): EIASeries(S.Electricity, F.Oil),
        (S.Electricity, F.Diesel): EIASeries(S.Electricity, F.Diesel),
        (S.Electricity, F.Gasoline): EIASeries(S.Transportation, F.Gasoline),
        # Residential
        (S.Residential, F.Oil): EIASeries(S.Commercial, F.Oil),
        (S.Residential, F.NaturalGas): EIASeries(S.Residential, F.NaturalGas),
        (S.Residential, F.LiquifiedPretroleumGas): residential_lpg,
        (S.Residential, F.Hydrogen): EIASeries(S.Industry, F.Hydrogen),
        # Commercial
        (S.Commercial, F.Oil): EIASeries(S.Commercial, F.Oil),
        (S.Commercial, F.NaturalGas): EIASeries(S.Commercial, F.NaturalGas),
        (S.Commercial, F.Hydrogen): EIASeries(S.Industry, F.Hydrogen),
        # Industry
        (S.Industry, F.Hydrogen): EIASeries(S.Industry, F.Hydrogen),
        (S.Industry, F.NaturalGas): EIASeries(S.Industry, F.NaturalGas),
        (S.Industry, F.HeavyFuelOil): EIASeries(S.Industry, F.HeavyFuelOil),
        (S.Industry, F.Coal): EIASeries(S.Industry, F.Coal),
        (S.Industry, F.Diesel): EIASeries(S.Industry, F.Diesel),
        (S.Industry, F.NaturalGasLiquids): EIASeries(S.Industry, F.Propane, 0.89),
        (S.Industry, F.PetroleumCoke): EIASeries(S.Industry, F.Coal),
        (S.Industry, F.Coke): EIASeries(S.Industry, F.Coal),
        # Transportation
        (S.Transportation, F.Hydrogen): EIASeries(S.Transportation, F.Hydrogen),
        (S.Transportation, F.NaturalGas): EIASeries(S.Transportation, F.NaturalGas),
        (S.Transportation, F.HeavyFuelOil): EIASeries(S.Transportation, F.HeavyFuelOil),
        (S.Transportation, F.LiquifiedPretroleumGas): EIASeries(
            S.Transportation, F.Propane
        ),
        (S.Transportation, F.Gasoline): EIASeries(S.Transportation, F.Gasoline),
        (S.Transportation, F.Diesel): EIASeries(S.Transportation, F.Diesel),
        (S.Transportation, F.CompressedNaturalGas): EIASeries(
            S.Transportation, F.NaturalGas, 0.89
        ),
        (S.Transportation, F.JetFuel): EIASeries(S.Transportation, F.JetFuel),
        (S.Transportation, F.MarineDieselOil): EIASeries(
            S.Transportation, F.Diesel, 0.9
        ),
        (S.Transportation, F.LiquifiedNaturalGas): EIASeries(
            S.Transportation, F.NaturalGas, 0.89
        ),
        # Agriculture: no EIA series of its own
        (S.Agriculture, F.NaturalGas): EIASeries(S.Industry, F.NaturalGas),
        (S.Agriculture, F.Diesel): EIASeries(S.Transportation, F.Diesel),
        (S.Agriculture, F.Propane): EIASeries(S.Transportation, F.Propane),
        (S.Agriculture, F.Gasoline): EIASeries(S.Transportation, F.Gasoline),
    }


def eia_price_table(
    eia: SourcePrices, reproduce_previous_price_errors: bool
) -> pd.DataFrame:
    """
    Price table of the (sector, fuel) priced by the EIA (see `eia_price_series`),
    every year of the data. The series are US averages: no region (every province).

    params:
    - eia: see `canoe.fuel.loaders.get_eia_energy_prices`

    Raises
    ------
    ValueError
        If a series is not in the data.
    """
    rows: list[dict[str, object]] = []
    for (sector, fuel), series in eia_price_series(
        reproduce_previous_price_errors
    ).items():
        eia_sector = series.sector.get_eia_sector()
        eia_fuel = series.fuel.get_eia_fuel(series.sector)
        selected = eia.prices.loc[
            (eia.prices["eia_sector"] == eia_sector)
            & (eia.prices["eia_fuel"] == eia_fuel)
        ]
        if selected.empty:
            raise ValueError(
                f"{str(sector).lower()} {fuel.get_desc_name()}: no EIA series "
                + f"'{eia_sector} : {eia_fuel}' ({eia.reference})"
            )
        description = f"{eia.reference}, {eia_sector} : {eia_fuel}" + (
            f" × {series.factor}" if series.factor != 1 else ""
        )
        rows.extend(
            {
                "region": None,
                "sector": sector,
                "fuel": fuel,
                "year": int(year),
                "price": float(price) * series.factor,
                "currency": eia.currency,
                "currency_year": eia.currency_year,
                "units": eia.units,
                "source": description,
            }
            for year, price in zip(selected["year"], selected["price"])
        )
    return _price_table(rows)


def atb_price_table(atb: SourcePrices) -> pd.DataFrame:
    """
    Price table of the (sector, fuel) priced by the fuel cost of the NREL ATB
    technology of the fuel (see `CANOEFuel.get_atb_technology`): no region and no
    year (every province and year).

    params:
    - atb: see `canoe.fuel.loaders.get_atb_fuel_prices`

    Raises
    ------
    ValueError
        If a technology is not in the data.
    """
    S, F = CANOESector, CANOEFuel
    priced = [
        (S.Electricity, F.GaseousBioenergy),
        (S.Electricity, F.SolidBioenergy),
        (S.Electricity, F.NaturalUranium),
        (S.Electricity, F.EnrichedUranium),
        (S.Residential, F.Wood),
        (S.Residential, F.BioEnergy),
        (S.Commercial, F.BioEnergy),
        (S.Industry, F.BioEnergy),
        (S.Industry, F.Wood),
        (S.Transportation, F.BioEnergy),
    ]
    atb_prices = dict(zip(atb.prices["atb_technology"], atb.prices["price"]))
    rows: list[dict[str, object]] = []
    for sector, fuel in priced:
        technology = fuel.get_atb_technology()
        if technology not in atb_prices:
            raise ValueError(f"{fuel.get_desc_name()}: no ATB price of {technology}")
        rows.append(
            {
                "region": None,
                "sector": sector,
                "fuel": fuel,
                "year": None,
                "price": float(atb_prices[technology]),
                "currency": atb.currency,
                "currency_year": atb.currency_year,
                "units": atb.units,
                "source": f"{atb.reference}, {technology} fuel cost (constant)",
            }
        )
    return _price_table(rows)


def fixed_price_table(fixed: SourcePrices) -> pd.DataFrame:
    """
    Price table of the (sector, fuel) priced by a fixed report price of the fuel: no
    region and no year (every province and year).

    params:
    - fixed: see `canoe.fuel.loaders.get_fixed_fuel_prices`

    Raises
    ------
    ValueError
        If a fuel is not in the data.
    """
    S, F = CANOESector, CANOEFuel
    priced = [
        (S.Transportation, F.Ethanol),
        (S.Transportation, F.RenewableDiesel),
        (S.Transportation, F.SyntheticJetFuel),
    ]
    fixed_prices = dict(zip(fixed.prices["fuel"], fixed.prices["price"]))
    rows: list[dict[str, object]] = []
    for sector, fuel in priced:
        if fuel not in fixed_prices:
            raise ValueError(f"{fuel.get_desc_name()}: no fixed price")
        rows.append(
            {
                "region": None,
                "sector": sector,
                "fuel": fuel,
                "year": None,
                "price": float(fixed_prices[fuel]),
                "currency": fixed.currency,
                "currency_year": fixed.currency_year,
                "units": fixed.units,
                "source": f"{fixed.reference} (constant)",
            }
        )
    return _price_table(rows)


def read_price_table(path: Path) -> pd.DataFrame:
    """
    The price table of a user's CSV file, with columns:

    - `region`: a province (code or name, see `CANOEProvince.from_str`), or empty
      for every province.
    - `sector`, `fuel`: see `CANOESector.from_str` and `CANOEFuel.from_str`.
    - `year`: the year the price applies to, or empty for every year.
    - `price`, `currency` (e.g. `CAD`, a column of the exchange table),
      `currency_year` and `units` (`$/GJ` or `$/MMBtu`).
    - `source` (optional): description, for notes; the file name if absent or empty.

    Rows with an empty region or year are logged as a warning.

    Raises
    ------
    ValueError
        If a column is missing or unknown, or a value can't be read (every such row
        is listed).
    """
    REQUIRED = [
        "region",
        "sector",
        "fuel",
        "year",
        "price",
        "currency",
        "currency_year",
        "units",
    ]
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    unknown = [c for c in raw.columns if c not in [*REQUIRED, "source"]]
    if missing or unknown:
        raise ValueError(
            f"{path}: missing columns {missing}, unknown columns {unknown}; expected "
            + f"{REQUIRED} and optionally 'source'"
        )

    def number(text: str, column: str) -> float:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(f"{column} {text!r} is not a finite number")
        return value

    def whole(text: str, column: str) -> int:
        value = number(text, column)
        if not value.is_integer():
            raise ValueError(f"{column} {text!r} is not a whole number")
        return int(value)

    def required(text: str, column: str) -> str:
        if not text:
            raise ValueError(f"empty {column}")
        return text

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for line, row in enumerate(raw.to_dict("records"), start=2):
        values = {column: str(value).strip() for column, value in row.items()}
        try:
            rows.append(
                {
                    "region": CANOEProvince.from_str(values["region"])
                    if values["region"]
                    else None,
                    "sector": CANOESector.from_str(
                        required(values["sector"], "sector")
                    ),
                    "fuel": CANOEFuel.from_str(required(values["fuel"], "fuel")),
                    "year": whole(values["year"], "year") if values["year"] else None,
                    "price": number(required(values["price"], "price"), "price"),
                    "currency": required(values["currency"], "currency"),
                    "currency_year": whole(
                        required(values["currency_year"], "currency_year"),
                        "currency_year",
                    ),
                    "units": required(values["units"], "units"),
                    "source": values.get("source") or path.name,
                }
            )
        except ValueError as error:
            errors.append(f"line {line}: {error}")
    if errors:
        raise ValueError(f"{path}: rows that can't be read:\n" + "\n".join(errors))

    no_region = sum(row["region"] is None for row in rows)
    no_year = sum(row["year"] is None for row in rows)
    if no_region or no_year:
        logger.warning(
            f"{path}: {no_region} rows with no region apply to every province, "
            + f"{no_year} rows with no year to every year"
        )
    return _price_table(rows)


def check_price_table(table: pd.DataFrame, name: str) -> None:
    """
    Check that `table` is a price table (see the module docstring): its columns, the
    types of its labels, finite prices, and no (region, sector, fuel, year) twice.

    Raises
    ------
    ValueError
        If it is not, naming the table and the rows at fault.
    """
    columns = list(_price_table([]).columns)
    if list(table.columns) != columns:
        raise ValueError(f"{name}: columns {list(table.columns)}, expected {columns}")
    bad = [
        not (
            (pd.isna(region) or isinstance(region, CANOEProvince))
            and isinstance(sector, CANOESector)
            and isinstance(fuel, CANOEFuel)
            and isinstance(price, float)
            and math.isfinite(price)
        )
        for region, sector, fuel, price in zip(
            table["region"], table["sector"], table["fuel"], table["price"]
        )
    ]
    if any(bad):
        raise ValueError(f"{name}: rows with invalid labels or prices:\n{table[bad]}")
    keys = ["region", "sector", "fuel", "year"]
    repeated = table.duplicated(keys, keep=False)
    if repeated.any():
        raise ValueError(f"{name}: prices given twice:\n{table.loc[repeated, keys]}")


def expand_price_table(
    table: pd.DataFrame, provinces: list[CANOEProvince], years: list[int]
) -> pd.DataFrame:
    """
    `table` with a row per province of `provinces` for the rows with no region, and
    per year of `years` for those with no year. Rows of other provinces are left
    out.

    Raises
    ------
    ValueError
        If a row with no region or year gives a price another row gives too.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> table = _price_table(
    ...     [
    ...         {"region": None, "sector": CANOESector.Commercial,
    ...          "fuel": CANOEFuel.NaturalGas, "year": None, "price": 1.0,
    ...          "currency": "CAD", "currency_year": 2020, "units": "$/GJ",
    ...          "source": "src"},
    ...     ]
    ... )
    >>> expanded = expand_price_table(table, [ON, QC], [2030, 2035])
    >>> [(r.short(), int(y)) for r, y in zip(expanded["region"], expanded["year"])]
    [('ON', 2030), ('ON', 2035), ('QC', 2030), ('QC', 2035)]
    """
    rows: list[dict[str, object]] = []
    for row in table.to_dict("records"):
        regions = provinces if pd.isna(row["region"]) else [row["region"]]
        row_years = years if pd.isna(row["year"]) else [int(row["year"])]
        rows.extend(
            {**row, "region": region, "year": year}
            for region in regions
            if region in provinces
            for year in row_years
        )
    expanded = _price_table(rows)
    keys = ["region", "sector", "fuel", "year"]
    repeated = expanded.duplicated(keys, keep=False)
    if repeated.any():
        raise ValueError(
            "Prices given twice, by a row with no region or year and another row:\n"
            + f"{expanded.loc[repeated, [*keys, 'source']]}"
        )
    return expanded


# 1 MMBtu = 1.055056 GJ; a price in $/GJ is in M$/PJ
_GJ_PER_MMBTU = 1.055056
_TO_DOLLARS_PER_GJ: dict[str, float] = {"$/MMBtu": 1 / _GJ_PER_MMBTU, "$/GJ": 1.0}

# Conversion of the previous fuel module (reproduce_previous_price_errors), to 2020
# CAD: $/MMBtu multiplied by 1.055, a fixed exchange rate, and a deflator per source
# year (the 2025 one for the EIA 2024 dollars). See FUEL_MODULE_BUGS.md
_PREVIOUS_MMBTU_MULTIPLIER = 1.055
_PREVIOUS_USD_TO_CAD = 1.22
_PREVIOUS_DEFLATORS: dict[int, float] = {2024: 0.877689699, 2022: 0.861446913}
PREVIOUS_MODULE_CURRENCY_YEAR = 2020
"""CAD year the previous module's conversion gives."""


def price_conversion_factor(
    currency: str,
    currency_year: int,
    units: str,
    model_currency_year: int,
    exchange: pd.DataFrame,
    inflation: pd.DataFrame,
    reproduce_previous_price_errors: bool,
) -> float:
    """
    Factor that converts prices in `currency` of `currency_year` per `units` to
    M$/PJ (= $/GJ) in CAD of `model_currency_year`.

    With `reproduce_previous_price_errors`, the previous module's conversion (to 2020
    CAD): USD prices per MMBtu times 1.055 × 1.22 × a fixed deflator, CAD prices
    unchanged.

    Raises
    ------
    ValueError
        If the units are unknown, or the previous conversion is asked for another
        currency year or prices it did not convert.

    Examples
    --------
    >>> factor = price_conversion_factor(
    ...     "USD", 2024, "$/MMBtu", 2020, pd.DataFrame(), pd.DataFrame(), True
    ... )
    >>> round(factor, 6)
    1.129674
    """
    if reproduce_previous_price_errors:
        if model_currency_year != PREVIOUS_MODULE_CURRENCY_YEAR:
            raise ValueError(
                "The previous module's price conversion gives "
                + f"{PREVIOUS_MODULE_CURRENCY_YEAR} CAD, not {model_currency_year} CAD"
            )
        if currency == "CAD" and currency_year == 2020:
            return 1.0
        if currency != "USD" or currency_year not in _PREVIOUS_DEFLATORS:
            raise ValueError(
                f"The previous module did not convert {currency} {currency_year} prices"
            )
        return (
            _PREVIOUS_MMBTU_MULTIPLIER
            * _PREVIOUS_USD_TO_CAD
            * _PREVIOUS_DEFLATORS[currency_year]
        )
    if units not in _TO_DOLLARS_PER_GJ:
        raise ValueError(
            f"Unknown price units {units!r}, expected one of {list(_TO_DOLLARS_PER_GJ)}"
        )
    return _TO_DOLLARS_PER_GJ[units] * currency_conversion_factor(
        currency,
        currency_year,
        model_currency_year,
        exchange,
        inflation,
    )


def convert_to_model_units(
    table: pd.DataFrame,
    model_currency_year: int,
    exchange: pd.DataFrame,
    inflation: pd.DataFrame,
    reproduce_previous_price_errors: bool,
) -> pd.DataFrame:
    """
    The price table `table` with its prices in M$/PJ of CAD of `model_currency_year`,
    each row converted from its own currency, year and units (see
    `price_conversion_factor`).

    Raises
    ------
    ValueError
        If a row can't be converted, naming its source.
    """
    factors: dict[tuple[str, int, str], float] = {}
    for key, source in zip(
        zip(table["currency"], table["currency_year"], table["units"]),
        table["source"],
    ):
        if key in factors:
            continue
        try:
            factors[key] = price_conversion_factor(
                str(key[0]),
                int(key[1]),
                str(key[2]),
                model_currency_year,
                exchange,
                inflation,
                reproduce_previous_price_errors,
            )
        except ValueError as error:
            raise ValueError(f"{source}: {error}") from error
    return table.assign(
        price=[
            price * factors[key]
            for price, key in zip(
                table["price"],
                zip(table["currency"], table["currency_year"], table["units"]),
            )
        ],
        currency="CAD",
        currency_year=model_currency_year,
        units="$/GJ",
    )


def combine_price_sources(
    tables: list[pd.DataFrame], fallback: PriceFallback
) -> pd.DataFrame:
    """
    The price tables `tables`, in priority order: each fuel (`PerFuel`) or each
    (region, sector, fuel) (`PerSeries`) takes all its years from the first table
    that has it.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> COM, IND = CANOESector.Commercial, CANOESector.Industry
    >>> def prices(rows, source):
    ...     return _price_table(
    ...         [
    ...             {"region": r, "sector": s, "fuel": CANOEFuel.NaturalGas,
    ...              "year": 2030, "price": 1.0, "currency": "CAD",
    ...              "currency_year": 2020, "units": "$/GJ", "source": source}
    ...             for r, s in rows
    ...         ]
    ...     )
    >>> regional = prices([(ON, COM)], "regional")
    >>> national = prices([(ON, COM), (ON, IND), (QC, COM)], "national")
    >>> combined = combine_price_sources([regional, national], PriceFallback.PerFuel)
    >>> list(combined["source"])
    ['regional']
    >>> combined = combine_price_sources([regional, national], PriceFallback.PerSeries)
    >>> list(combined["source"])
    ['regional', 'national', 'national']
    """
    columns = {
        PriceFallback.PerFuel: ["fuel"],
        PriceFallback.PerSeries: ["region", "sector", "fuel"],
    }[fallback]
    taken: set[tuple[object, ...]] = set()
    kept: list[pd.DataFrame] = []
    for table in tables:
        keys = list(zip(*(table[column] for column in columns)))
        kept.append(table.loc[[key not in taken for key in keys]])
        taken.update(keys)
    return _price_table([]) if not kept else pd.concat(kept, ignore_index=True)

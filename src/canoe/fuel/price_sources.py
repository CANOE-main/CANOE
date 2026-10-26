"""
Fuel price sources: from the prices each loader returns, in the source's own labels,
currency and units, to the harmonized prices the rest of the module uses.

Each source goes through two steps:

1. `convert_to_model_units`: its prices to M$/PJ (= $/GJ) of CAD of the model
   currency year.
2. `harmonize_<source>_prices`: its labels to CANOE regions, sectors and fuels, with
   the proxies of the source (e.g. agriculture takes the industrial natural gas
   series of the EIA).

Every harmonizer returns the same frame, the **harmonized prices**: one row per
(region, sector, fuel, year) with columns `region` (`CANOEProvince`), `sector`
(`CANOESector`), `fuel` (`CANOEFuel`), `year`, `price` (M$/PJ of CAD of the model
currency year) and `source` (description, for notes). The prices are delivered
prices, used as they are for the import and distribution costs (see
`canoe.fuel.prices`). `combine_price_sources` merges the harmonized prices of the
sources configured, in priority order.

A new source needs a loader (`canoe.fuel.loaders`), a harmonizer here, a member of
`FuelPriceSource` and its case in `canoe.fuel.build`.
"""

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.currency import currency_conversion_factor
from canoe.fuel.loaders import SourcePrices


class FuelPriceSource(StrEnum):
    """A source of delivered fuel prices."""

    EIA = "eia"
    """EIA Annual Energy Outlook, Table 3: delivered prices by sector and fuel (US
    average, projected), with proxies for the series it lacks. Fossil fuels and
    hydrogen."""

    ATB = "atb"
    """NREL ATB: fuel cost of the biopower and nuclear plants, constant. Bioenergy,
    wood and uranium."""

    Fixed = "fixed"
    """Fixed report prices, constant. Ethanol, renewable diesel and synthetic jet
    fuel."""


class PriceFallback(StrEnum):
    """How the sources configured, in priority order, share the prices."""

    PerFuel = "per_fuel"
    """Each fuel takes all its prices (every region and sector) from the first source
    that prices it, so the prices of a fuel never mix sources."""

    PerSeries = "per_series"
    """Each (region, sector, fuel) takes its prices from the first source that has
    it, so a source fills the gaps of the ones before it."""


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
    source: SourcePrices,
    model_currency_year: int,
    exchange: pd.DataFrame,
    inflation: pd.DataFrame,
    reproduce_previous_price_errors: bool,
) -> float:
    """
    Factor that converts the prices of `source` to M$/PJ (= $/GJ) in CAD of
    `model_currency_year`.

    With `reproduce_previous_price_errors`, the previous module's conversion (to 2020
    CAD): USD prices per MMBtu times 1.055 × 1.22 × a fixed deflator, CAD prices
    unchanged.

    Raises
    ------
    ValueError
        If the units are unknown, or the previous conversion is asked for another
        currency year or a source it did not convert.

    Examples
    --------
    >>> source = SourcePrices(pd.DataFrame(), "USD", 2024, "$/MMBtu", "EIA")
    >>> round(price_conversion_factor(source, 2020, pd.DataFrame(), pd.DataFrame(), True), 6)
    1.129674
    """
    if reproduce_previous_price_errors:
        if model_currency_year != PREVIOUS_MODULE_CURRENCY_YEAR:
            raise ValueError(
                "The previous module's price conversion gives "
                + f"{PREVIOUS_MODULE_CURRENCY_YEAR} CAD, not {model_currency_year} CAD"
            )
        if source.currency == "CAD" and source.currency_year == 2020:
            return 1.0
        if source.currency != "USD" or source.currency_year not in _PREVIOUS_DEFLATORS:
            raise ValueError(
                f"The previous module did not convert {source.currency} "
                + f"{source.currency_year} prices ({source.reference})"
            )
        return (
            _PREVIOUS_MMBTU_MULTIPLIER
            * _PREVIOUS_USD_TO_CAD
            * _PREVIOUS_DEFLATORS[source.currency_year]
        )
    if source.units not in _TO_DOLLARS_PER_GJ:
        raise ValueError(f"Unknown price units {source.units!r} ({source.reference})")
    return _TO_DOLLARS_PER_GJ[source.units] * currency_conversion_factor(
        source.currency,
        source.currency_year,
        model_currency_year,
        exchange,
        inflation,
    )


def convert_to_model_units(
    source: SourcePrices,
    model_currency_year: int,
    exchange: pd.DataFrame,
    inflation: pd.DataFrame,
    reproduce_previous_price_errors: bool,
) -> SourcePrices:
    """`source` with its prices in M$/PJ of CAD of `model_currency_year`, see
    `price_conversion_factor`."""
    factor = price_conversion_factor(
        source,
        model_currency_year,
        exchange,
        inflation,
        reproduce_previous_price_errors,
    )
    return SourcePrices(
        prices=source.prices.assign(price=source.prices["price"] * factor),
        currency="CAD",
        currency_year=model_currency_year,
        units="$/GJ",
        reference=source.reference,
    )


def _check_model_units(source: SourcePrices) -> None:
    """Harmonizers take prices already converted by `convert_to_model_units`."""
    if source.currency != "CAD" or source.units != "$/GJ":
        raise ValueError(
            f"{source.reference}: prices in {source.currency} {source.units}, "
            + "expected CAD $/GJ (see convert_to_model_units)"
        )


def _harmonized_prices(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["region", "sector", "fuel", "year", "price", "source"]
    )


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


def harmonize_eia_prices(
    eia: SourcePrices,
    provinces: list[CANOEProvince],
    reproduce_previous_price_errors: bool,
) -> pd.DataFrame:
    """
    Harmonized prices of the (sector, fuel) priced by the EIA (see
    `eia_price_series`), every year of the data. The series are US averages: every
    province takes the same price.

    params:
    - eia: see `canoe.fuel.loaders.get_eia_energy_prices`, converted to the model
      units (see `convert_to_model_units`)

    Raises
    ------
    ValueError
        If the prices are not in the model units, or a series is not in the data.
    """
    _check_model_units(eia)
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
                "region": province,
                "sector": sector,
                "fuel": fuel,
                "year": int(year),
                "price": float(price) * series.factor,
                "source": description,
            }
            for province in provinces
            for year, price in zip(selected["year"], selected["price"])
        )
    return _harmonized_prices(rows)


def harmonize_atb_prices(
    atb: SourcePrices, provinces: list[CANOEProvince], years: list[int]
) -> pd.DataFrame:
    """
    Harmonized prices of the (sector, fuel) priced by the fuel cost of the NREL ATB
    technology of the fuel (see `CANOEFuel.get_atb_technology`), the same in every
    province and in each of `years`.

    params:
    - atb: see `canoe.fuel.loaders.get_atb_fuel_prices`, converted to the model
      units (see `convert_to_model_units`)

    Raises
    ------
    ValueError
        If the prices are not in the model units, or a technology is not in the data.
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
    _check_model_units(atb)
    atb_prices = dict(zip(atb.prices["atb_technology"], atb.prices["price"]))
    rows: list[dict[str, object]] = []
    for sector, fuel in priced:
        technology = fuel.get_atb_technology()
        if technology not in atb_prices:
            raise ValueError(f"{fuel.get_desc_name()}: no ATB price of {technology}")
        rows.extend(
            {
                "region": province,
                "sector": sector,
                "fuel": fuel,
                "year": year,
                "price": float(atb_prices[technology]),
                "source": f"{atb.reference}, {technology} fuel cost (constant)",
            }
            for province in provinces
            for year in years
        )
    return _harmonized_prices(rows)


def harmonize_fixed_prices(
    fixed: SourcePrices, provinces: list[CANOEProvince], years: list[int]
) -> pd.DataFrame:
    """
    Harmonized prices of the (sector, fuel) priced by a fixed report price of the
    fuel, the same in every province and in each of `years`.

    params:
    - fixed: see `canoe.fuel.loaders.get_fixed_fuel_prices`, converted to the model
      units (see `convert_to_model_units`)

    Raises
    ------
    ValueError
        If the prices are not in the model units, or a fuel is not in the data.
    """
    S, F = CANOESector, CANOEFuel
    priced = [
        (S.Transportation, F.Ethanol),
        (S.Transportation, F.RenewableDiesel),
        (S.Transportation, F.SyntheticJetFuel),
    ]
    _check_model_units(fixed)
    fixed_prices = dict(zip(fixed.prices["fuel"], fixed.prices["price"]))
    rows: list[dict[str, object]] = []
    for sector, fuel in priced:
        if fuel not in fixed_prices:
            raise ValueError(f"{fuel.get_desc_name()}: no fixed price")
        rows.extend(
            {
                "region": province,
                "sector": sector,
                "fuel": fuel,
                "year": year,
                "price": float(fixed_prices[fuel]),
                "source": f"{fixed.reference} (constant)",
            }
            for province in provinces
            for year in years
        )
    return _harmonized_prices(rows)


def combine_price_sources(
    harmonized: list[pd.DataFrame], fallback: PriceFallback
) -> pd.DataFrame:
    """
    The harmonized prices of the sources in `harmonized`, in priority order: each
    fuel (`PerFuel`) or each (region, sector, fuel) (`PerSeries`) takes all its
    years from the first source that has it.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> COM, IND = CANOESector.Commercial, CANOESector.Industry
    >>> NG = CANOEFuel.NaturalGas
    >>> def prices(rows, source):
    ...     return _harmonized_prices(
    ...         [
    ...             {"region": r, "sector": s, "fuel": NG, "year": 2030, "price": 1.0,
    ...              "source": source}
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
    for prices in harmonized:
        keys = list(zip(*(prices[column] for column in columns)))
        kept.append(prices.loc[[key not in taken for key in keys]])
        taken.update(keys)
    return _harmonized_prices([]) if not kept else pd.concat(kept, ignore_index=True)

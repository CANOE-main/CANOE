"""
Fuel prices: where the delivered price of each (sector, fuel) comes from, and how it
is split between the import and the distribution technologies.

Each fuel is supplied in two steps, `F_ethos -> F_IMP_<FUEL> -> F_<fuel> ->
F_<S>_<FUEL> -> <S>_<fuel>`. The price a sector pays for a fuel (its delivered price)
is the variable cost of the import technology plus that of its distribution
technology:

- The import cost of a fuel is the lowest delivered price among the entries of that
  fuel in `DELIVERED_PRICE_SOURCES`, whether their sectors run or not. The table is
  fixed, so the import cost doesn't change with the sectors that run.
- Each distribution technology costs its sector's delivered price minus the import
  cost.

Every unit imported goes through exactly one distribution technology (both with
efficiency 1), so the split only decides where the cost is reported: the price each
sector pays, and the model's solution, are the same whatever the split.
"""

from dataclasses import dataclass

import pandas as pd

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.currency import currency_conversion_factor
from canoe.common.validation import ValidationBehavior, handle_validation_issue
from canoe.fuel.loaders import SourcePrices


@dataclass(frozen=True)
class EIASeries:
    """
    An EIA AEO Table 3 'Energy Prices' series (real 2024 $/MMBtu), named by the CANOE
    sector and fuel it is read for (see `CANOESector.get_eia_sector` and
    `CANOEFuel.get_eia_fuel`).
    """

    sector: CANOESector
    fuel: CANOEFuel
    factor: float = 1.0
    """Multiplier on the series, for fuels priced as a fraction of another."""


@dataclass(frozen=True)
class ATBFuelCost:
    """The fuel cost of the NREL ATB technology of `fuel` (see
    `CANOEFuel.get_atb_technology`), constant over the periods."""

    fuel: CANOEFuel


@dataclass(frozen=True)
class FixedPrice:
    """A fixed price of `fuel` from a report (ethanol, renewable diesel, SPK),
    constant over the periods."""

    fuel: CANOEFuel


PriceSource = EIASeries | ATBFuelCost | FixedPrice

_S = CANOESector
_F = CANOEFuel

DELIVERED_PRICE_SOURCES: dict[tuple[CANOESector, CANOEFuel], PriceSource] = {
    # Electricity. No electricity sector yet, but its prices set import costs
    (_S.Electricity, _F.GaseousBioenergy): ATBFuelCost(_F.GaseousBioenergy),
    (_S.Electricity, _F.SolidBioenergy): ATBFuelCost(_F.SolidBioenergy),
    (_S.Electricity, _F.NaturalGas): EIASeries(_S.Electricity, _F.NaturalGas),
    (_S.Electricity, _F.Coal): EIASeries(_S.Industry, _F.Coal),
    (_S.Electricity, _F.Oil): EIASeries(_S.Electricity, _F.Oil),
    (_S.Electricity, _F.Diesel): EIASeries(_S.Electricity, _F.Diesel),
    (_S.Electricity, _F.NaturalUranium): ATBFuelCost(_F.NaturalUranium),
    (_S.Electricity, _F.EnrichedUranium): ATBFuelCost(_F.EnrichedUranium),
    (_S.Electricity, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
    # Residential
    (_S.Residential, _F.Oil): EIASeries(_S.Commercial, _F.Oil),
    (_S.Residential, _F.NaturalGas): EIASeries(_S.Residential, _F.NaturalGas),
    (_S.Residential, _F.LiquifiedPretroleumGas): EIASeries(_S.Residential, _F.Propane),
    (_S.Residential, _F.Wood): ATBFuelCost(_F.Wood),
    (_S.Residential, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Residential, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    # Commercial
    (_S.Commercial, _F.Oil): EIASeries(_S.Commercial, _F.Oil),
    (_S.Commercial, _F.NaturalGas): EIASeries(_S.Commercial, _F.NaturalGas),
    (_S.Commercial, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Commercial, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    # Industry
    (_S.Industry, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Industry, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    (_S.Industry, _F.NaturalGas): EIASeries(_S.Industry, _F.NaturalGas),
    (_S.Industry, _F.HeavyFuelOil): EIASeries(_S.Industry, _F.HeavyFuelOil),
    (_S.Industry, _F.Coal): EIASeries(_S.Industry, _F.Coal),
    (_S.Industry, _F.Diesel): EIASeries(_S.Industry, _F.Diesel),
    (_S.Industry, _F.NaturalGasLiquids): EIASeries(_S.Industry, _F.Propane, 0.89),
    (_S.Industry, _F.PetroleumCoke): EIASeries(_S.Industry, _F.Coal),
    (_S.Industry, _F.Wood): ATBFuelCost(_F.Wood),
    (_S.Industry, _F.Coke): EIASeries(_S.Industry, _F.Coal),
    # Transportation
    (_S.Transportation, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Transportation, _F.Hydrogen): EIASeries(_S.Transportation, _F.Hydrogen),
    (_S.Transportation, _F.NaturalGas): EIASeries(_S.Transportation, _F.NaturalGas),
    (_S.Transportation, _F.HeavyFuelOil): EIASeries(_S.Transportation, _F.HeavyFuelOil),
    (_S.Transportation, _F.LiquifiedPretroleumGas): EIASeries(
        _S.Transportation, _F.Propane
    ),
    (_S.Transportation, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
    (_S.Transportation, _F.Ethanol): FixedPrice(_F.Ethanol),
    (_S.Transportation, _F.Diesel): EIASeries(_S.Transportation, _F.Diesel),
    (_S.Transportation, _F.RenewableDiesel): FixedPrice(_F.RenewableDiesel),
    (_S.Transportation, _F.CompressedNaturalGas): EIASeries(
        _S.Transportation, _F.NaturalGas, 0.89
    ),
    (_S.Transportation, _F.JetFuel): EIASeries(_S.Transportation, _F.JetFuel),
    (_S.Transportation, _F.SyntheticJetFuel): FixedPrice(_F.SyntheticJetFuel),
    (_S.Transportation, _F.MarineDieselOil): EIASeries(
        _S.Transportation, _F.Diesel, 0.9
    ),
    (_S.Transportation, _F.LiquifiedNaturalGas): EIASeries(
        _S.Transportation, _F.NaturalGas, 0.89
    ),
    # Agriculture: no EIA series of its own
    (_S.Agriculture, _F.NaturalGas): EIASeries(_S.Industry, _F.NaturalGas),
    (_S.Agriculture, _F.Diesel): EIASeries(_S.Transportation, _F.Diesel),
    (_S.Agriculture, _F.Propane): EIASeries(_S.Transportation, _F.Propane),
    (_S.Agriculture, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
}
"""
Source of the delivered price of each (sector, fuel), reproducing the previous fuel
module (its `fuel_list.csv` rows and `_calc_cost` proxies). A (sector, fuel) that
is not here has no price. See `FUEL_MODULE_BUGS.md` for the quirks kept (proxy
series, the 0.89 and 0.9 factors).
"""

_PREVIOUS_MODULE_PRICE_SOURCE_ERRORS: dict[
    tuple[CANOESector, CANOEFuel], PriceSource
] = {
    # The previous module compared the output commodity with the technology name,
    # so residential LPG always took the transportation propane series
    (_S.Residential, _F.LiquifiedPretroleumGas): EIASeries(
        _S.Transportation, _F.Propane
    ),
}


def get_delivered_price_sources(
    reproduce_previous_price_errors: bool,
) -> dict[tuple[CANOESector, CANOEFuel], PriceSource]:
    """
    `DELIVERED_PRICE_SOURCES`, with the errors of the previous fuel module when
    `reproduce_previous_price_errors`.

    Examples
    --------
    >>> key = (CANOESector.Residential, CANOEFuel.LiquifiedPretroleumGas)
    >>> get_delivered_price_sources(False)[key]
    EIASeries(sector=<CANOESector.Residential: 'RES'>, fuel=Propane, factor=1.0)
    >>> get_delivered_price_sources(True)[key]
    EIASeries(sector=<CANOESector.Transportation: 'TRP'>, fuel=Propane, factor=1.0)
    """
    if not reproduce_previous_price_errors:
        return dict(DELIVERED_PRICE_SOURCES)
    return {**DELIVERED_PRICE_SOURCES, **_PREVIOUS_MODULE_PRICE_SOURCE_ERRORS}


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


def check_price_sources(
    imports: list[CANOEFuelImport],
    sources: dict[tuple[CANOESector, CANOEFuel], PriceSource],
    behavior: ValidationBehavior,
) -> list[CANOEFuelImport]:
    """
    The `imports` whose (sector, fuel) has a price source. The others are reported
    with `behavior` and left out: they are not supplied.

    Examples
    --------
    >>> imports = [
    ...     CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas, ()),
    ...     CANOEFuelImport(CANOESector.Industry, CANOEFuel.Other, ()),
    ... ]
    >>> [i.fuel for i in check_price_sources(imports, DELIVERED_PRICE_SOURCES, "warning")]
    [NaturalGas]
    """
    missing = [i for i in imports if (i.sector, i.fuel) not in sources]
    if missing:
        handle_validation_issue(
            "No price for "
            + ", ".join(
                f"{str(i.sector).lower()} {i.fuel.get_desc_name()}" for i in missing
            )
            + "; not supplied",
            behavior,
        )
    return [i for i in imports if (i.sector, i.fuel) in sources]


def compute_delivered_prices(
    sources: dict[tuple[CANOESector, CANOEFuel], PriceSource],
    fuels: list[CANOEFuel],
    projection_years: dict[int, int],
    eia: SourcePrices,
    atb: SourcePrices,
    fixed: SourcePrices,
) -> pd.DataFrame:
    """
    Delivered price of every entry of `sources` whose fuel is in `fuels`, in each
    model period. Entries of sectors that don't run are included: they take part in
    the import cost (see `split_import_and_distribution`).

    params:
    - projection_years: model period -> year its prices are read at, see
      `canoe.common.periods.projection_year_by_period`. ATB and fixed prices are
      constant.
    - eia, atb, fixed: the prices of each source, already in the model units (see
      `price_conversion_factor`), see the loaders of `canoe.fuel.loaders`

    Returns one row per (sector, fuel, period) with columns `sector`, `fuel`,
    `period`, `year` (year read), `price` (the units of the sources) and `source`
    (description, for notes).

    Raises
    ------
    ValueError
        If an entry names a series or year the data does not have.
    """
    eia_prices = {
        (s, f, int(y)): float(p)
        for s, f, y, p in zip(
            eia.prices["eia_sector"],
            eia.prices["eia_fuel"],
            eia.prices["year"],
            eia.prices["price"],
        )
    }
    atb_prices = dict(zip(atb.prices["atb_technology"], atb.prices["price"]))
    fixed_prices = dict(zip(fixed.prices["fuel"], fixed.prices["price"]))

    rows: list[dict[str, object]] = []
    for (sector, fuel), source in sources.items():
        if fuel not in fuels:
            continue
        if isinstance(source, EIASeries):
            eia_sector = source.sector.get_eia_sector()
            eia_fuel = source.fuel.get_eia_fuel(source.sector)
            description = f"{eia.reference}, {eia_sector} : {eia_fuel}" + (
                f" × {source.factor}" if source.factor != 1 else ""
            )
            for period, year in projection_years.items():
                key = (eia_sector, eia_fuel, year)
                if key not in eia_prices:
                    raise ValueError(
                        f"{str(sector).lower()} {fuel.get_desc_name()}: no EIA price "
                        + f"'{eia_sector} : {eia_fuel}' in {year}"
                    )
                rows.append(
                    {
                        "sector": sector,
                        "fuel": fuel,
                        "period": period,
                        "year": year,
                        "price": eia_prices[key] * source.factor,
                        "source": description,
                    }
                )
            continue
        if isinstance(source, ATBFuelCost):
            technology = source.fuel.get_atb_technology()
            if technology not in atb_prices:
                raise ValueError(
                    f"{fuel.get_desc_name()}: no ATB price of {technology}"
                )
            price = float(atb_prices[technology])
            description = f"{atb.reference}, {technology} fuel cost (constant)"
        else:
            if source.fuel not in fixed_prices:
                raise ValueError(f"{fuel.get_desc_name()}: no fixed price")
            price = float(fixed_prices[source.fuel])
            description = f"{fixed.reference} (constant)"
        rows.extend(
            {
                "sector": sector,
                "fuel": fuel,
                "period": period,
                "year": year,
                "price": price,
                "source": description,
            }
            for period, year in projection_years.items()
        )
    return pd.DataFrame(
        rows, columns=["sector", "fuel", "period", "year", "price", "source"]
    )


def split_import_and_distribution(
    delivered_prices: pd.DataFrame,
    imports: list[CANOEFuelImport],
    cost_notes_suffix: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Import and distribution costs of the fuel imports, in their provinces.

    The import cost of a fuel in a period is the lowest delivered price among its
    entries in `delivered_prices` (all sectors of the price table, running or not);
    each distribution technology costs its sector's delivered price minus it. A
    fuel is imported in the provinces where some sector takes it.

    params:
    - delivered_prices: see `compute_delivered_prices`. Must have every (sector,
      fuel) imported.
    - imports: the fuel imports supplied, one per (sector, fuel)
    - cost_notes_suffix: appended to the notes, e.g. the units and projection year

    Returns
    - import costs: one row per (region, period, fuel) imported, with columns
      `region`, `period`, `fuel`, `cost` and `notes`, see
      `canoe.fuel.entities.build_fuel_supply`
    - distribution costs: one row per (region, period, sector, fuel) of the
      imports, with the same columns plus `sector`

    Examples
    --------
    >>> delivered = pd.DataFrame(
    ...     {
    ...         "sector": [CANOESector.Electricity, CANOESector.Commercial],
    ...         "fuel": [CANOEFuel.NaturalGas, CANOEFuel.NaturalGas],
    ...         "period": [2025, 2025],
    ...         "year": [2030, 2030],
    ...         "price": [3.9, 10.1],
    ...         "source": ["EP", "COM"],
    ...     }
    ... )
    >>> imports, distribution = split_import_and_distribution(
    ...     delivered,
    ...     [
    ...         CANOEFuelImport(
    ...             CANOESector.Commercial, CANOEFuel.NaturalGas, (CANOEProvince.ONTARIO,)
    ...         )
    ...     ],
    ...     "",
    ... )
    >>> list(zip(imports["period"], imports["cost"]))
    [(2025, 3.9)]
    >>> [round(cost, 6) for cost in distribution["cost"]]
    [6.2]
    """
    prices = {
        (s, f, int(p)): (float(price), str(source))
        for s, f, p, price, source in zip(
            delivered_prices["sector"],
            delivered_prices["fuel"],
            delivered_prices["period"],
            delivered_prices["price"],
            delivered_prices["source"],
        )
    }
    periods = sorted({int(p) for p in delivered_prices["period"]})
    # Provinces where each fuel is imported: where some sector takes it
    fuel_provinces: dict[CANOEFuel, set[CANOEProvince]] = {}
    for fuel_import in imports:
        fuel_provinces.setdefault(fuel_import.fuel, set()).update(fuel_import.provinces)

    # Lowest delivered price of each fuel and period, and the sector setting it
    cheapest: dict[tuple[CANOEFuel, int], tuple[CANOESector, float, str]] = {}
    for (sector, fuel, period), (price, source) in prices.items():
        key = (fuel, period)
        if key not in cheapest or price < cheapest[key][1]:
            cheapest[key] = (sector, price, source)

    import_rows: list[dict[str, object]] = []
    for fuel, provinces in fuel_provinces.items():
        for period in periods:
            sector, price, source = cheapest[(fuel, period)]
            notes = (
                f"Lowest delivered price of {fuel.get_desc_name()} among the sectors "
                + f"priced: {str(sector).lower()} ({source}){cost_notes_suffix}"
            )
            import_rows.extend(
                {
                    "region": province,
                    "period": period,
                    "fuel": fuel,
                    "cost": price,
                    "notes": notes,
                }
                for province in CANOEProvince
                if province in provinces
            )

    distribution_rows: list[dict[str, object]] = []
    for fuel_import in imports:
        sector, fuel = fuel_import.sector, fuel_import.fuel
        for period in periods:
            price, source = prices[(sector, fuel, period)]
            notes = (
                f"Delivered price of {fuel.get_desc_name()} to the "
                + f"{str(sector).lower()} sector ({source}) minus the import "
                + f"cost{cost_notes_suffix}"
            )
            distribution_rows.extend(
                {
                    "region": province,
                    "period": period,
                    "sector": sector,
                    "fuel": fuel,
                    "cost": price - cheapest[(fuel, period)][1],
                    "notes": notes,
                }
                for province in fuel_import.provinces
            )

    return (
        pd.DataFrame(
            import_rows, columns=["region", "period", "fuel", "cost", "notes"]
        ),
        pd.DataFrame(
            distribution_rows,
            columns=["region", "period", "sector", "fuel", "cost", "notes"],
        ),
    )

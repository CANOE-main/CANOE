"""
Fuel prices: the delivered price of each (region, sector, fuel) in each period, and
how it is split between the import and the distribution technologies.

The prices come from the price tables of the sources configured, combined and in
the model units (see `canoe.fuel.price_sources`), used as they are. Each fuel is supplied in two steps,
`F_ethos -> F_IMP_<FUEL> -> F_<fuel> -> F_<S>_<FUEL> -> <S>_<fuel>`. The price a
sector pays for a fuel (its delivered price) is the variable cost of the import
technology plus that of its distribution technology:

- The import cost of a fuel in a region is the lowest delivered price of that fuel
  among the sectors priced in the region, whether they run or not, so it doesn't
  change with the sectors that run.
- Each distribution technology costs its sector's delivered price minus the import
  cost.

Every unit imported goes through exactly one distribution technology (both with
efficiency 1), so the split only decides where the cost is reported: the price each
sector pays, and the model's solution, are the same whatever the split.
"""

import pandas as pd

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.validation import ValidationBehavior, handle_validation_issue


def check_price_coverage(
    imports: list[CANOEFuelImport],
    prices: pd.DataFrame,
    behavior: ValidationBehavior,
) -> list[CANOEFuelImport]:
    """
    The `imports` in the provinces where their (sector, fuel) has a price in
    `prices` (price table, see `canoe.fuel.price_sources`). The others are
    reported with `behavior` and left out: they are not supplied there. Imports
    priced in none of their provinces are left out.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> NG = CANOEFuel.NaturalGas
    >>> prices = pd.DataFrame(
    ...     {"region": [ON], "sector": [CANOESector.Commercial], "fuel": [NG]}
    ... )
    >>> imports = [
    ...     CANOEFuelImport(CANOESector.Commercial, NG, (ON, QC)),
    ...     CANOEFuelImport(CANOESector.Industry, CANOEFuel.Other, (ON,)),
    ... ]
    >>> for i in check_price_coverage(imports, prices, "warning"):
    ...     print(i.sector, i.fuel, [p.short() for p in i.provinces])
    Commercial NaturalGas ['ON']
    """
    priced = set(zip(prices["region"], prices["sector"], prices["fuel"]))
    supplied: list[CANOEFuelImport] = []
    missing: list[str] = []
    for fuel_import in imports:
        sector, fuel = fuel_import.sector, fuel_import.fuel
        provinces = tuple(
            p for p in fuel_import.provinces if (p, sector, fuel) in priced
        )
        unpriced = [p.short() for p in fuel_import.provinces if p not in provinces]
        if unpriced:
            missing.append(
                f"{str(sector).lower()} {fuel.get_desc_name()} ({', '.join(unpriced)})"
            )
        if provinces:
            supplied.append(CANOEFuelImport(sector, fuel, provinces))
    if missing:
        handle_validation_issue(
            "No price for " + ", ".join(missing) + "; not supplied there", behavior
        )
    return supplied


def delivered_prices_by_period(
    prices: pd.DataFrame,
    fuels: list[CANOEFuel],
    projection_years: dict[int, int],
) -> pd.DataFrame:
    """
    Delivered price of every (region, sector, fuel) of `prices` whose fuel is in
    `fuels`, in each model period. Sectors that don't run are included: they take
    part in the import cost (see `split_import_and_distribution`).

    params:
    - prices: price table with every region and year explicit, in M$/PJ, see
      `canoe.fuel.price_sources`
    - projection_years: model period -> year its prices are read at, see
      `canoe.common.periods.projection_year_by_period`

    Returns one row per (region, sector, fuel, period) with columns `region`,
    `sector`, `fuel`, `period`, `year` (year read), `price` (M$/PJ) and `source`
    (description, for notes).

    Raises
    ------
    ValueError
        If a (region, sector, fuel) has no price in a year read.
    """
    by_year = {
        (r, s, f, int(y)): (float(p), str(source))
        for r, s, f, y, p, source in zip(
            prices["region"],
            prices["sector"],
            prices["fuel"],
            prices["year"],
            prices["price"],
            prices["source"],
        )
        if f in fuels
    }
    series = dict.fromkeys((r, s, f) for r, s, f, _ in by_year)

    rows: list[dict[str, object]] = []
    for region, sector, fuel in series:
        for period, year in projection_years.items():
            key = (region, sector, fuel, year)
            if key not in by_year:
                raise ValueError(
                    f"{str(sector).lower()} {fuel.get_desc_name()} in "
                    + f"{region.short()}: no price in {year}"
                )
            price, source = by_year[key]
            rows.append(
                {
                    "region": region,
                    "sector": sector,
                    "fuel": fuel,
                    "period": period,
                    "year": year,
                    "price": price,
                    "source": source,
                }
            )
    return pd.DataFrame(
        rows,
        columns=["region", "sector", "fuel", "period", "year", "price", "source"],
    )


def split_import_and_distribution(
    delivered_prices: pd.DataFrame,
    imports: list[CANOEFuelImport],
    cost_notes_suffix: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Import and distribution costs of the fuel imports, in their provinces.

    The import cost of a fuel in a region and period is the lowest delivered price
    among its entries in `delivered_prices` for that region (all sectors priced,
    running or not); each distribution technology costs its sector's delivered price
    minus it. A fuel is imported in the provinces where some sector takes it.

    params:
    - delivered_prices: see `delivered_prices_by_period`. Must have every (sector,
      fuel) imported in each of its provinces.
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
    >>> ON = CANOEProvince.ONTARIO
    >>> delivered = pd.DataFrame(
    ...     {
    ...         "region": [ON, ON],
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
    ...     [CANOEFuelImport(CANOESector.Commercial, CANOEFuel.NaturalGas, (ON,))],
    ...     "",
    ... )
    >>> list(zip(imports["period"], imports["cost"]))
    [(2025, 3.9)]
    >>> [round(cost, 6) for cost in distribution["cost"]]
    [6.2]
    """
    prices = {
        (r, s, f, int(p)): (float(price), str(source))
        for r, s, f, p, price, source in zip(
            delivered_prices["region"],
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

    # Lowest delivered price of each region, fuel and period, and the sector setting it
    cheapest: dict[
        tuple[CANOEProvince, CANOEFuel, int], tuple[CANOESector, float, str]
    ] = {}
    for (region, sector, fuel, period), (price, source) in prices.items():
        key = (region, fuel, period)
        if key not in cheapest or price < cheapest[key][1]:
            cheapest[key] = (sector, price, source)

    import_rows: list[dict[str, object]] = []
    for fuel, provinces in fuel_provinces.items():
        for period in periods:
            for province in CANOEProvince:
                if province not in provinces:
                    continue
                sector, price, source = cheapest[(province, fuel, period)]
                import_rows.append(
                    {
                        "region": province,
                        "period": period,
                        "fuel": fuel,
                        "cost": price,
                        "notes": f"Lowest delivered price of {fuel.get_desc_name()} "
                        + f"among the sectors priced: {str(sector).lower()} "
                        + f"({source}){cost_notes_suffix}",
                    }
                )

    distribution_rows: list[dict[str, object]] = []
    for fuel_import in imports:
        sector, fuel = fuel_import.sector, fuel_import.fuel
        for period in periods:
            for province in fuel_import.provinces:
                price, source = prices[(province, sector, fuel, period)]
                distribution_rows.append(
                    {
                        "region": province,
                        "period": period,
                        "sector": sector,
                        "fuel": fuel,
                        "cost": price - cheapest[(province, fuel, period)][1],
                        "notes": f"Delivered price of {fuel.get_desc_name()} to the "
                        + f"{str(sector).lower()} sector ({source}) minus the import "
                        + f"cost{cost_notes_suffix}",
                    }
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

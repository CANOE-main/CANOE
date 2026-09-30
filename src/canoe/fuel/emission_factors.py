"""
Emission factors of the fuel technologies: combustion factors by sector and fuel, on
the distribution technologies, and upstream factors by fuel, on the imports.
"""

import pandas as pd

from canoe.common import CANOEFuel, CANOESector

COMBUSTION_FACTOR_PROXIES: dict[
    tuple[CANOESector, CANOEFuel], tuple[CANOESector, CANOEFuel]
] = {
    # The previous module's file has no agriculture gasoline; agriculture diesel and
    # propane already take the transportation values
    (CANOESector.Agriculture, CANOEFuel.Gasoline): (
        CANOESector.Transportation,
        CANOEFuel.Gasoline,
    ),
}
"""(sector, fuel) with no combustion factors of its own -> (sector, fuel) whose
factors it takes."""


def add_combustion_factor_proxies(
    combustion_factors: pd.DataFrame,
    reproduce_previous_emission_errors: bool,
) -> pd.DataFrame:
    """
    Combustion factors with the rows of `COMBUSTION_FACTOR_PROXIES` added, unless
    `reproduce_previous_emission_errors` (the previous module left them out).

    Parameters
    ----------
    combustion_factors : pd.DataFrame
        Columns `sector`, `fuel`, `emission`, `factor`, `notes`, `reference`, see
        `canoe.fuel.loaders.get_combustion_emission_factors`.
    reproduce_previous_emission_errors : bool
        Leave the proxied (sector, fuel) without factors, as the previous module.

    Raises
    ------
    ValueError
        If a proxied (sector, fuel) already has factors (the proxy is no longer
        needed) or its proxy has none.

    Examples
    --------
    >>> factors = pd.DataFrame(
    ...     {
    ...         "sector": [CANOESector.Transportation],
    ...         "fuel": [CANOEFuel.Gasoline],
    ...         "emission": ["CO2"],
    ...         "factor": [65.4],
    ...         "notes": [""],
    ...         "reference": ["NS QRV"],
    ...     }
    ... )
    >>> proxied = add_combustion_factor_proxies(factors, False)
    >>> [(str(s), str(f), x) for s, f, x in proxied[["sector", "fuel", "factor"]].values]
    [('Transportation', 'Gasoline', 65.4), ('Agriculture', 'Gasoline', 65.4)]
    >>> len(add_combustion_factor_proxies(factors, True))
    1
    """
    if reproduce_previous_emission_errors:
        return combustion_factors

    # NOTE: enum columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== CANOESector.X` compares against str(CANOESector.X) (the name), never matching
    def rows_of(sector: CANOESector, fuel: CANOEFuel) -> pd.Series:
        return combustion_factors["sector"].isin([sector]) & combustion_factors[
            "fuel"
        ].isin([fuel])

    proxied: list[pd.DataFrame] = []
    for (sector, fuel), (proxy_sector, proxy_fuel) in COMBUSTION_FACTOR_PROXIES.items():
        if bool(rows_of(sector, fuel).any()):
            raise ValueError(
                f"{sector} {fuel.get_desc_name()} has combustion factors; remove its "
                + "entry from COMBUSTION_FACTOR_PROXIES"
            )
        proxy = combustion_factors.loc[rows_of(proxy_sector, proxy_fuel)]
        if proxy.empty:
            raise ValueError(
                f"No combustion factors of {proxy_sector} {proxy_fuel.get_desc_name()}"
                + f", the proxy of {sector} {fuel.get_desc_name()}"
            )
        proxied.append(
            proxy.assign(
                sector=sector,
                fuel=fuel,
                notes=f"Factors of {str(proxy_sector).lower()} "
                + f"{proxy_fuel.get_desc_name()}, no {str(sector).lower()} data",
            )
        )
    return pd.concat([combustion_factors, *proxied], ignore_index=True)

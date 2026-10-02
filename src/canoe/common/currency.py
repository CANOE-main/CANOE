"""
Currency conversion to the model currency: Canadian dollars of the model currency
year (`CANOEBaseConfig.model_currency_year`), with the exchange and inflation tables
of `canoe.common.loaders.get_exchange_and_inflation_tables`.
"""

import pandas as pd


def currency_conversion_factor(
    currency: str,
    currency_year: int,
    model_currency_year: int,
    exchange: pd.DataFrame,
    inflation: pd.DataFrame,
) -> float:
    """
    Factor that converts an amount in `currency` of `currency_year` to CAD of
    `model_currency_year`: the exchange rate and GDP deflator of the currency year,
    over those of the model currency year (as commercial's AEO cost conversion).

    Parameters
    ----------
    currency : str
        Column of the exchange table, e.g. `USD`.
    currency_year : int
        Year of the amount (real dollars of that year).
    model_currency_year : int
        Year of the CAD converted to.
    exchange, inflation : pd.DataFrame
        CAD per unit of each currency, and price indices (column `gdp_deflator`), by
        year (index).

    Raises
    ------
    ValueError
        If a year or the currency is not in the tables.

    Examples
    --------
    >>> exchange = pd.DataFrame({"CAD": [1.0, 1.0], "USD": [1.25, 1.2]}, index=[2020, 2024])
    >>> inflation = pd.DataFrame({"gdp_deflator": [1.0, 0.9]}, index=[2020, 2024])
    >>> round(currency_conversion_factor("USD", 2024, 2020, exchange, inflation), 6)
    1.08
    >>> currency_conversion_factor("CAD", 2020, 2020, exchange, inflation)
    1.0
    """
    for year in (currency_year, model_currency_year):
        if year not in exchange.index or year not in inflation.index:
            raise ValueError(f"No exchange rate or GDP deflator for {year}")
    if currency not in exchange.columns:
        raise ValueError(
            f"No exchange rate for {currency}; currencies: {list(exchange.columns)}"
        )
    model_factor = float(exchange.loc[model_currency_year, "CAD"]) * float(
        inflation.loc[model_currency_year, "gdp_deflator"]
    )
    return (
        float(exchange.loc[currency_year, currency])
        * float(inflation.loc[currency_year, "gdp_deflator"])
        / model_factor
    )

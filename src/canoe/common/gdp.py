"""
GDP growth used to project demands, shared by all sectors.

Sectors scale base-year demands with the projected GDP of the CER Canada's Energy
Future macro indicators (see `canoe.common.loaders.get_cer_gdp`). The scenario and the
point of each period where GDP is read are chosen once in the base configuration
(`CANOEBaseConfig`) and inherited by every sector, so all demands grow consistently.
"""

from enum import StrEnum

import pandas as pd


class CERScenario(StrEnum):
    """
    Scenario of the CER Canada's Energy Future 2023 macro indicators.

    Values are the scenario names as they appear in the CER data.
    """

    GlobalNetZero = "Global Net-zero"
    """Canada and the rest of the world reach net-zero emissions by 2050."""

    CanadaNetZero = "Canada Net-zero"
    """Canada reaches net-zero emissions by 2050; the rest of the world acts less."""

    CurrentMeasures = "Current Measures"
    """Only climate policies in place today, no further action."""


class GDPProjectionPoint(StrEnum):
    """
    Year of each model period at which projected GDP scales the base-year demand.

    A model period runs from its first year to the next year in `future_periods`,
    e.g. with `future_periods = [2025, 2030, ..., 2050]` period 2025 covers 2025-2029.
    """

    PeriodEnd = "period_end"
    """GDP at the end of the period (the next year in `future_periods`), relative to
    the year of the base demand data."""

    PeriodStart = "period_start"
    """GDP at the first year of the period, relative to the year of the base demand
    data."""

    Legacy = "legacy"
    """GDP at the first year of the period relative to the first model period, so the
    first period keeps the base-year demand unchanged. Reproduces the previous
    agriculture module; to be removed."""


def gdp_growth_by_period(
    gdp_index: pd.DataFrame,
    future_periods: list[int],
    projection_point: GDPProjectionPoint,
) -> dict[int, float]:
    """
    GDP growth factor of each model period, to multiply base-year demands by.

    Parameters
    ----------
    gdp_index : pd.DataFrame
        GDP by year (index) in column `gdp`, relative to the year of the base demand
        data, see `canoe.common.loaders.get_cer_gdp`.
    future_periods : list[int]
        Temoa's `time_future`: the model periods followed by the end of the horizon.
    projection_point : GDPProjectionPoint
        Year of each period at which GDP is read.

    Returns
    -------
    dict[int, float]
        Model period -> growth factor.

    Examples
    --------
    >>> gdp_index = pd.DataFrame(
    ...     {"gdp": [1.0, 1.1, 1.2, 1.5]}, index=[2022, 2025, 2030, 2035]
    ... )
    >>> gdp_growth_by_period(gdp_index, [2025, 2030, 2035], GDPProjectionPoint.PeriodEnd)
    {2025: 1.2, 2030: 1.5}
    >>> gdp_growth_by_period(gdp_index, [2025, 2030, 2035], GDPProjectionPoint.PeriodStart)
    {2025: 1.1, 2030: 1.2}
    >>> growth = gdp_growth_by_period(gdp_index, [2025, 2030, 2035], GDPProjectionPoint.Legacy)
    >>> {period: round(factor, 4) for period, factor in growth.items()}
    {2025: 1.0, 2030: 1.0909}
    """
    model_periods = future_periods[:-1]
    gdp = gdp_index["gdp"]

    if projection_point == GDPProjectionPoint.PeriodEnd:
        return {
            period: float(gdp.loc[end_year])
            for period, end_year in zip(model_periods, future_periods[1:])
        }
    if projection_point == GDPProjectionPoint.PeriodStart:
        return {period: float(gdp.loc[period]) for period in model_periods}
    first_period_gdp = float(gdp.loc[model_periods[0]])
    return {
        period: float(gdp.loc[period]) / first_period_gdp for period in model_periods
    }

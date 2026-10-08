"""
Model periods and the year of each period a projected series is read at, shared by
all modules.

`future_periods` are the model periods, the ones modules write data for. Temoa also
needs the end of the horizon as one more period with no data (its `time_future` is
the model periods followed by it): the initializer writes `future_periods[-1] +
period_step` for it, and modules never write data for it.

A model period runs from December 31st of its label year to December 31st of the
next label (the end of the horizon for the last one), e.g. with `future_periods =
[2025, 2030, ..., 2045]` and `period_step = 5` period 2025 covers the years
2026-2030 and period 2045 the years 2046-2050: no data of 2025 itself falls in
period 2025. Modules that read yearly projections (prices, ...) pick one year per
period with a `ProjectionPoint`, chosen once in the base configuration so all modules
agree.
"""

from enum import StrEnum


class ProjectionPoint(StrEnum):
    """Year of each model period at which a projected series is read."""

    PeriodEnd = "period_end"
    """The last year of the period: the next label in `future_periods`, or the end of
    the horizon for the last period (2030 for period 2025)."""

    PeriodStart = "period_start"
    """The label year of the period (2025 for period 2025). The period starts on
    December 31st of that year, so this is the year just before the period."""


def period_end_years(future_periods: list[int], period_step: int) -> dict[int, int]:
    """
    Year each model period ends: the next label in `future_periods`, and the end of
    the horizon (`future_periods[-1] + period_step`) for the last period.

    Examples
    --------
    >>> period_end_years([2025, 2030, 2040], 5)
    {2025: 2030, 2030: 2040, 2040: 2045}
    """
    end_of_horizon = future_periods[-1] + period_step
    return dict(zip(future_periods, [*future_periods[1:], end_of_horizon]))


def horizon_length(future_periods: list[int], period_step: int) -> int:
    """
    Years from the first model period to the end of the horizon
    (`future_periods[-1] + period_step`). A technology with a single vintage, the
    first period, serves every period with this lifetime.

    Examples
    --------
    >>> horizon_length([2025, 2030, 2035, 2040, 2045], 5)
    25
    """
    return future_periods[-1] + period_step - future_periods[0]


def projection_year_by_period(
    future_periods: list[int], period_step: int, projection_point: ProjectionPoint
) -> dict[int, int]:
    """
    Year each model period reads a projected series at.

    Parameters
    ----------
    future_periods : list[int]
        The model periods.
    period_step : int
        Length of the last period, see `period_end_years`.
    projection_point : ProjectionPoint
        Year of each period to read.

    Returns
    -------
    dict[int, int]
        Model period -> year.

    Examples
    --------
    >>> projection_year_by_period([2025, 2030, 2040], 5, ProjectionPoint.PeriodEnd)
    {2025: 2030, 2030: 2040, 2040: 2045}
    >>> projection_year_by_period([2025, 2030, 2040], 5, ProjectionPoint.PeriodStart)
    {2025: 2025, 2030: 2030, 2040: 2040}
    """
    if projection_point == ProjectionPoint.PeriodEnd:
        return period_end_years(future_periods, period_step)
    return {period: period for period in future_periods}


def existing_stock_vintages(
    lifetime: float, first_period: int, period_step: int
) -> dict[int, float]:
    """
    Vintages of a stock that stands at the start of the first model period, and the
    share of the stock in each.

    The stock is spread evenly over the years it was built in: the vintages are the
    multiples of `period_step` still alive in `first_period` (built less than
    `lifetime` years before it), each standing for `period_step` years of the stock.
    If `first_period` is not a multiple of `period_step`, it is a vintage too,
    standing for the years since the last multiple. The newest vintage is labelled
    `first_period - 1`: existing vintages must come before the first model period.

    Parameters
    ----------
    lifetime : float
        Lifetime of the technology, in years.
    first_period : int
        First model period, the year the stock stands at.
    period_step : int
        Years between vintages.

    Returns
    -------
    dict[int, float]
        Vintage -> share of the stock (adding up to 1), oldest first.

    Examples
    --------
    A 13-year lifetime: the 2015, 2020 and 2025 builds are alive in 2025, and the
    newest is labelled 2024.

    >>> existing_stock_vintages(13, 2025, 5)
    {2015: 0.333..., 2020: 0.333..., 2024: 0.333...}

    Off the grid of multiples, the first period stands for the years since the last
    one (2025 for 2027):

    >>> existing_stock_vintages(13, 2027, 5)
    {2015: 0.294..., 2020: 0.294..., 2025: 0.294..., 2026: 0.117...}

    A lifetime shorter than a step keeps all the stock in the newest vintage:

    >>> existing_stock_vintages(3, 2025, 5)
    {2024: 1.0}
    """
    last_multiple = first_period - first_period % period_step
    # Years of the stock each vintage stands for: the multiples still alive in the
    # first period stand for a whole step each ...
    years_built = {
        vintage: period_step
        for vintage in range(last_multiple, int(first_period - lifetime), -period_step)
    }
    # ... and the first period itself for the years since the last multiple
    if first_period not in years_built:
        years_built[first_period] = first_period - last_multiple
    # The newest vintage is labelled the year before the first period
    years_built[first_period - 1] = years_built.get(
        first_period - 1, 0
    ) + years_built.pop(first_period)

    total_years = sum(years_built.values())
    return {
        vintage: years / total_years for vintage, years in sorted(years_built.items())
    }

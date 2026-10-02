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

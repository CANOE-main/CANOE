"""
Which year of each model period a projected series is read at, shared by all modules.

A model period runs from December 31st of its label year to December 31st of the
next year in `future_periods`, e.g. with `future_periods = [2025, 2030, ..., 2050]`
period 2025 covers the years 2026-2030: no data of 2025 itself falls in period 2025.
Modules that read yearly projections (prices, ...) pick one year per period with a
`ProjectionPoint`, chosen once in the base configuration so all modules agree.
"""

from enum import StrEnum


class ProjectionPoint(StrEnum):
    """Year of each model period at which a projected series is read."""

    PeriodEnd = "period_end"
    """The last year of the period: the next label in `future_periods` (2030 for
    period 2025)."""

    PeriodStart = "period_start"
    """The label year of the period (2025 for period 2025). The period starts on
    December 31st of that year, so this is the year just before the period."""


def projection_year_by_period(
    future_periods: list[int], projection_point: ProjectionPoint
) -> dict[int, int]:
    """
    Year each model period reads a projected series at.

    Parameters
    ----------
    future_periods : list[int]
        Temoa's `time_future`: the model periods followed by the end of the horizon.
    projection_point : ProjectionPoint
        Year of each period to read.

    Returns
    -------
    dict[int, int]
        Model period -> year.

    Examples
    --------
    >>> projection_year_by_period([2025, 2030, 2040], ProjectionPoint.PeriodEnd)
    {2025: 2030, 2030: 2040}
    >>> projection_year_by_period([2025, 2030, 2040], ProjectionPoint.PeriodStart)
    {2025: 2025, 2030: 2030}
    """
    model_periods = future_periods[:-1]
    if projection_point == ProjectionPoint.PeriodEnd:
        return dict(zip(model_periods, future_periods[1:]))
    return {period: period for period in model_periods}

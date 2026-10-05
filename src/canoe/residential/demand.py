"""
Projection of the residential demands from their base-year values. Nothing in here
touches the database.
"""

from enum import StrEnum


class DemandDriver(StrEnum):
    """Projected series that scales the base-year demands."""

    Population = "population"
    """Provincial population (StatCan projections), as the previous module."""

    GDP = "gdp"
    """National GDP (CER Canada's Energy Future), as the other sectors."""

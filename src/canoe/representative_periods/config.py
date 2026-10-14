"""Configuration of the representative periods step."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from canoe.representative_periods.clusterings import Clustering


class RepresentativePeriodsConfig(BaseModel):
    """
    Reduce a full-year database to representative days, from a clustering computed
    elsewhere.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    clustering: Clustering
    """The clustering to apply (see `canoe.representative_periods.clusterings`)."""

    demand_preservation: Literal["hourly", "annual"] = "hourly"
    """What the reduced database keeps of each demand. The representative days
    cannot keep both:

    - `hourly`: the hourly values of the representative days; the annual demand
      changes;
    - `annual`: the annual demand; the hourly values are rescaled."""

    dsd_threshold: float = Field(default=0.01, ge=0, lt=1)
    """Share of each demand's distribution set to zero, taken from its smallest
    values (per region, period and demand). With `hourly` preservation, the annual
    demand drops by up to this share."""

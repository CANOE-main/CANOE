"""Pydantic model mirroring the structure of config.yaml."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# Arbitrarily nested directories of csv timeseries files. Dict keys are directory
# names, leaves are lists of csv file (column) names. A leaf directory with nothing
# selected yet (e.g. `temoa-canada:` with no items) parses to None.
# Declared with the PEP 695 `type` statement (rather than a plain assignment) so
# pydantic can recognise the self-reference and build a recursive schema instead
# of expanding it indefinitely.
type TimeseriesTree = dict[str, "TimeseriesTree | list[str] | None"]


class PCAGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    columns: list[str]
    n_components: int
    scale: bool = True

    def as_dict(self) -> dict:  # pyright: ignore[reportMissingTypeArgument]
        return self.__dict__  # pyright: ignore[reportReturnType]


class ExtremePeriods(BaseModel):
    """Under each extreme period type, the timeseries vectors that should apply it."""

    model_config = ConfigDict(extra="forbid")

    max_peak: list[str] | None = None
    min_peak: list[str] | None = None
    max_mean: list[str] | None = None
    min_mean: list[str] | None = None


class CustomFeature(BaseModel):
    """Calls a method of feature_identification.py with the given parameters."""

    model_config = ConfigDict(extra="allow")

    method: Literal["max_mean_period"]
    days_in_period: int
    timeseries: str

    def as_dict(self) -> dict:  # pyright: ignore[reportMissingTypeArgument]
        return self.__dict__  # pyright: ignore[reportReturnType]


class RepresentativePeriodsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path
    show_plots: bool = False
    days_per_period: int = 1
    disaggregate_multiday: bool = True
    demand_preservation: Literal["hourly", "annual"] = "hourly"
    dsd_threshold: float = 0.01
    final_periods: int
    test_periods: list[int] | None = None

    use_pca: bool = True
    pca_groups: list[PCAGroup] = Field(default_factory=list)

    force_days: list[int] | None = None
    extreme_periods: ExtremePeriods = Field(default_factory=ExtremePeriods)
    custom_features: list[CustomFeature] | None = None

    day_to_index: int = -1
    clustering_method: Literal[
        "averaging",
        "k_means",
        "k_medoids",
        "k_maxoids",
        "hierarchical",
        "adjacent_periods",
    ] = "hierarchical"

    timeseries: TimeseriesTree
    model_years: list[int]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RepresentativePeriodsConfig":
        with open(path) as stream:
            raw = yaml.safe_load(stream)
        return cls.model_validate(raw)

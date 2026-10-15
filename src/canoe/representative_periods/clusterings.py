"""
Where a clustering comes from: one variant per way of producing clusterings.

Each variant identifies a clustering and knows how to load its
`RepresentativeSeasonMapping`. `Clustering` is the tagged union of the variants,
dispatched on `kind`; to add a methodology, add a variant and extend the union.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from canoe.representative_periods.mapping import RepresentativeSeasonMapping


class TsamCollection(BaseModel):
    """
    A clustering precomputed with tsam, from a collection with one clustering for
    each number of clusters, plus forced and extreme days added on top as tsam adds
    them (`extremePeriodMethod="new_cluster_center"`).

    A collection is a folder with:

    - `assignments.csv`: a `season` column and one column per number of clusters,
      whose cells are the season representing the season of the row;
    - `features.csv`: the clustered features as tsam scaled them (to [0, 1]), with
      `season` and `hour` columns, to add forced and extreme days;
    - `accuracy.csv`: tsam's accuracy indicators for each number of clusters;
    - `clustering.toml`: how the collection was made, for people to read.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    kind: Literal["tsam_collection"] = "tsam_collection"
    """Selects this variant."""
    collection: str
    """Name of the collection (its folder), e.g. `weather2018-hierarchical-pca6`."""
    collections_dir: Path | None = None
    """Folder holding the collection; the collections packaged with canoe
    (`canoe/representative_periods/data/clusterings`) if left out."""
    n_periods: PositiveInt
    """Number of representative days, forced and extreme days included: as in the
    old module, tsam clusters the days into `n_periods` minus the number of forced
    and extreme days."""
    forced_days: list[str] = []
    """Seasons added as representative days (tsam's `addManual`)."""
    max_peak: list[str] = []
    """Features whose day with the highest hourly value is added (`addPeakMax`)."""
    min_peak: list[str] = []
    """Features whose day with the lowest hourly value is added (`addPeakMin`)."""
    max_mean: list[str] = []
    """Features whose day with the highest daily mean is added (`addMeanMax`)."""
    min_mean: list[str] = []
    """Features whose day with the lowest daily mean is added (`addMeanMin`)."""

    @model_validator(mode="after")
    def _check_clusters_left(self) -> "TsamCollection":
        if self.n_clusters() < 1:
            raise ValueError(
                f"{self.n_periods} periods leave no cluster after the "
                + f"{self.n_periods - self.n_clusters()} forced and extreme days"
            )
        return self

    def n_clusters(self) -> int:
        """Number of clusters tsam makes before adding forced and extreme days."""
        return (
            self.n_periods
            - len(self.forced_days)
            - len(self.max_peak)
            - len(self.min_peak)
            - len(self.max_mean)
            - len(self.min_mean)
        )

    def folder(self) -> Traversable:
        """The folder of the collection, wherever canoe is installed."""
        root = (
            self.collections_dir
            if self.collections_dir is not None
            else files("canoe.representative_periods").joinpath("data/clusterings")
        )
        folder = root.joinpath(self.collection)
        if not folder.is_dir():
            available = sorted(p.name for p in root.iterdir() if p.is_dir())
            raise ValueError(
                f"No collection {self.collection!r} in {root}; available: {available}"
            )
        return folder

    def load_mapping(self) -> RepresentativeSeasonMapping:
        """
        The clustering into `n_clusters()` from `assignments.csv`, with the forced
        and extreme days added from `features.csv`.
        """
        path = self.folder().joinpath("assignments.csv")
        with path.open("rb") as f:
            table = pd.read_csv(f, index_col="season", dtype=str)
        column = str(self.n_clusters())
        if column not in table.columns:
            raise ValueError(
                f"{path} has no clustering for {column} clusters "
                + f"(columns {table.columns[0]} to {table.columns[-1]})"
            )
        representative_of = table[column].to_dict()
        missing = [s for s, r in representative_of.items() if pd.isna(r)]
        if missing:
            raise ValueError(
                f"{path}, column {column}: no representative for {missing}"
            )
        representative_of = {str(s): str(r) for s, r in representative_of.items()}

        if self.n_clusters() < self.n_periods:
            with self.folder().joinpath("features.csv").open("rb") as f:
                # round_trip: the distances must be tsam's to the last bit
                features = pd.read_csv(
                    f, index_col=["season", "hour"], float_precision="round_trip"
                )
            representative_of = add_extreme_days(
                representative_of,
                features,
                forced_days=self.forced_days,
                max_peak=self.max_peak,
                min_peak=self.min_peak,
                max_mean=self.max_mean,
                min_mean=self.min_mean,
            )
            n_found = len(set(representative_of.values()))
            if n_found < self.n_periods:
                logger.warning(
                    f"{self.n_periods} periods asked, {n_found} found: "
                    + f"{self.n_periods - n_found} forced or extreme day(s) were "
                    + "already representative days"
                )
        return RepresentativeSeasonMapping(representative_of=representative_of)


# Add new variants here, e.g. a single mapping file made by another method
Clustering = Annotated[TsamCollection, Field(discriminator="kind")]


def add_extreme_days(
    representative_of: dict[str, str],
    features: pd.DataFrame,
    forced_days: list[str],
    max_peak: list[str],
    min_peak: list[str],
    max_mean: list[str],
    min_mean: list[str],
) -> dict[str, str]:
    """
    Add forced and extreme days to a clustering, as tsam's `_addExtremePeriods`
    does with `extremePeriodMethod="new_cluster_center"`.

    tsam clusters first and adds these days afterwards, and its cluster centres
    are then the scaled features of the representative days (it rescales them
    later), so this gives tsam's result from the stored clustering. tsam's quirks
    are kept:

    - a day that is already a representative is skipped (one period fewer);
    - the forced days come first, then the extremes by feature, in the order of
      the columns of `features`, and for each feature max peak, min peak, max mean,
      min mean;
    - each day moves to the last added day it is closer to than to its
      representative, not to the closest one.

    Parameters
    ----------
    representative_of
        Season -> the season that represents it, before adding the days.
    features
        The clustered features as tsam scaled them, indexed by season and hour.
    forced_days
        Seasons to add.
    max_peak, min_peak, max_mean, min_mean
        Features (columns of `features`) whose day with the highest or lowest
        hourly value or daily mean is added.

    Examples
    --------
    >>> features = pd.DataFrame(
    ...     {"x": [0.0, 0.0, 0.1, 0.1, 0.8, 0.8, 1.0, 0.9]},
    ...     index=pd.MultiIndex.from_product(
    ...         [["D001", "D002", "D003", "D004"], [0, 1]], names=["season", "hour"]
    ...     ),
    ... )
    >>> base = {"D001": "D002", "D002": "D002", "D003": "D002", "D004": "D002"}
    >>> add_extreme_days(base, features, [], ["x"], [], [], [])
    {'D001': 'D002', 'D002': 'D002', 'D003': 'D004', 'D004': 'D004'}
    """
    unknown_days = sorted(set(forced_days) - set(representative_of))
    if unknown_days:
        raise ValueError(f"Forced days not in the clustering: {unknown_days}")
    unknown_features = sorted(
        set(max_peak + min_peak + max_mean + min_mean) - set(features.columns)
    )
    if unknown_features:
        raise ValueError(
            f"Extremes of features that were not clustered: {unknown_features} "
            + f"(clustered: {list(features.columns)})"
        )

    # One row per day, columns (feature, hour) in tsam's order
    profiles = features.unstack("hour")
    centres = [
        profiles.loc[r].tolist() for r in sorted(set(representative_of.values()))
    ]

    added: list[str] = []

    def add(day: str) -> None:
        # tsam skips days already added and days whose profile is a centre's
        if day not in added and profiles.loc[day].tolist() not in centres:
            added.append(day)

    for day in forced_days:
        add(day)
    for feature in features.columns:
        hourly = profiles[feature]
        if feature in max_peak:
            add(str(hourly.max(axis=1).idxmax()))
        if feature in min_peak:
            add(str(hourly.min(axis=1).idxmin()))
        if feature in max_mean:
            add(str(hourly.mean(axis=1).idxmax()))
        if feature in min_mean:
            add(str(hourly.mean(axis=1).idxmin()))

    def distance(a: str, b: str) -> float:
        # tsam's arithmetic: Python's sum over the squared differences
        return sum((profiles.loc[a].to_numpy() - profiles.loc[b].to_numpy()) ** 2)

    new_representative_of = dict(representative_of)
    for day, representative in representative_of.items():
        to_representative = distance(day, representative)
        for extreme in added:
            # An added day never moves to another added day
            if day in added and day != extreme:
                continue
            if distance(day, extreme) < to_representative:
                new_representative_of[day] = extreme
    return new_representative_of

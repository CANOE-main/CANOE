"""
Where a clustering comes from: one variant per way of producing clusterings.

Each variant identifies a clustering and gives its `RepresentativeSeasonMapping`
(`mapping()`). `Clustering` is the tagged union of the variants, dispatched on
`kind`; to add a methodology, add a variant and extend the union.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from canoe.representative_periods.compute import (
    ClusterMethod,
    cluster_days,
    daily_table,
    extreme_days,
    find_series,
    load_series,
    principal_components,
    select_series,
)
from canoe.representative_periods.mapping import RepresentativeSeasonMapping


class TsamCollection(BaseModel):
    """
    A clustering precomputed with tsam, from a collection with one clustering for
    each number of clusters, plus forced days added on top as tsam adds them
    (`extremePeriodMethod="new_cluster_center"`).

    A collection is a folder with:

    - `assignments.csv`: a `season` column and one column per number of clusters,
      whose cells are the season representing the season of the row;
    - `features.csv`: the clustered features as tsam scaled them (to [0, 1]), with
      `season` and `hour` columns, to add forced days;
    - `accuracy.csv`: tsam's accuracy indicators for each number of clusters;
    - `clustering.toml`: how the collection was made, for people to read.

    Only the clustered features are stored (principal components for the packaged
    collection), so extreme days are not offered: see `TsamClustering`.
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
    """Number of representative days, forced days included: the stored clustering
    into `n_periods` minus the number of forced days is used."""
    forced_days: list[str] = []
    """Seasons added as representative days (tsam's `addManual`)."""

    @model_validator(mode="after")
    def _check_forced_days(self) -> "TsamCollection":
        if len(set(self.forced_days)) < len(self.forced_days):
            raise ValueError(f"Repeated forced days: {self.forced_days}")
        if len(self.forced_days) >= self.n_periods:
            raise ValueError(
                f"{self.n_periods} periods leave no cluster after "
                + f"{len(self.forced_days)} forced days"
            )
        return self

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

    def mapping(self) -> RepresentativeSeasonMapping:
        """
        The stored clustering into `n_periods` minus the forced days, from
        `assignments.csv`, with the forced days added from `features.csv`.
        """
        path = self.folder().joinpath("assignments.csv")
        with path.open("rb") as f:
            table = pd.read_csv(f, index_col="season", dtype=str)
        column = str(self.n_periods - len(self.forced_days))
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

        if self.forced_days:
            with self.folder().joinpath("features.csv").open("rb") as f:
                # round_trip: the distances must be tsam's to the last bit
                features = pd.read_csv(
                    f, index_col=["season", "hour"], float_precision="round_trip"
                )
            representative_of = add_forced_days(
                representative_of, features, self.forced_days
            )
        _warn_if_fewer(representative_of, self.n_periods)
        return RepresentativeSeasonMapping(representative_of=representative_of)


class TsamClustering(BaseModel):
    """
    Days clustered with tsam when the pipeline runs, on the series of `data_dir`.

    The selected series are standardised and reduced to their principal components
    (if `pca_components` is set), the days are clustered into `n_periods`
    minus the forced and extreme days, each cluster represented by its medoid day,
    and tsam then adds the forced and extreme days
    (`extremePeriodMethod="new_cluster_center"`).
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    kind: Literal["tsam"] = "tsam"
    """Selects this variant."""
    data_dir: Path
    """Folder with the series: one CSV per series, at any depth, named after the
    series (`on/on_temperature.csv` is `on_temperature`), with a `time` column (with
    UTC offsets) and one column of values."""
    weather_year: int
    """Year of the series to cluster; its days are labelled by their date in EST
    (`Dnnn` is day nnn of the year)."""
    include: list[str] | None = None
    """Patterns of the series to cluster, matched against their paths in `data_dir`
    without `.csv` (e.g. `*_temperature`, `on/*`). All series if neither this nor
    `exclude` is set."""
    exclude: list[str] | None = None
    """Patterns of the series not to cluster; all the others are clustered."""
    pca_components: PositiveInt | None = None
    """Number of principal components of the standardised series that are
    clustered; the series themselves if left out."""
    method: ClusterMethod = "hierarchical"
    """tsam clustering method; each cluster is represented by its medoid day."""
    n_periods: PositiveInt
    """Number of representative days, forced and extreme days included."""
    forced_days: list[str] = []
    """Seasons added as representative days."""
    max_peak: list[str] = []
    """Series (of `data_dir`, clustered or not) whose day with the highest hourly
    value is added."""
    min_peak: list[str] = []
    """Series whose day with the lowest hourly value is added."""
    max_mean: list[str] = []
    """Series whose day with the highest daily mean is added."""
    min_mean: list[str] = []
    """Series whose day with the lowest daily mean is added."""

    @model_validator(mode="after")
    def _check_selection(self) -> "TsamClustering":
        if self.include is not None and self.exclude is not None:
            raise ValueError("Set `include` or `exclude`, not both")
        return self

    def mapping(self) -> RepresentativeSeasonMapping:
        """Cluster the days of `weather_year`."""
        series_files = find_series(self.data_dir)
        clustered = select_series(series_files, self.include, self.exclude)
        extremes = self.max_peak + self.min_peak + self.max_mean + self.min_mean
        unknown = sorted(set(extremes) - set(series_files))
        if unknown:
            raise ValueError(f"Extremes of series not in {self.data_dir}: {unknown}")
        names = clustered + [n for n in dict.fromkeys(extremes) if n not in clustered]
        table = daily_table(
            load_series(self.data_dir, series_files, names), self.weather_year
        )

        seasons = table.index.unique("season")
        unknown = sorted(set(self.forced_days) - set(seasons))
        if unknown:
            raise ValueError(f"Forced days not among the days clustered: {unknown}")
        found = extreme_days(
            table, self.max_peak, self.min_peak, self.max_mean, self.min_mean
        )
        if found:
            logger.info(f"Extreme days: {found}")
        # A day forced or extreme several times counts once
        added_days = list(dict.fromkeys(self.forced_days + found))
        n_clusters = self.n_periods - len(added_days)
        if n_clusters < 1:
            raise ValueError(
                f"{self.n_periods} periods leave no cluster after "
                + f"{len(added_days)} forced and extreme days"
            )

        features = table.loc[:, clustered]
        if self.pca_components is not None:
            features = principal_components(features, self.pca_components)
        logger.info(
            f"Clustering {len(seasons)} days of {self.weather_year} over "
            + f"{len(clustered)} series"
            + (f" ({self.pca_components} components)" if self.pca_components else "")
        )
        representative_of = cluster_days(features, n_clusters, self.method, added_days)
        _warn_if_fewer(representative_of, self.n_periods)
        return RepresentativeSeasonMapping(representative_of=representative_of)


Clustering = Annotated[TsamCollection | TsamClustering, Field(discriminator="kind")]


def _warn_if_fewer(representative_of: dict[str, str], n_periods: int) -> None:
    n_found = len(set(representative_of.values()))
    if n_found < n_periods:
        logger.warning(
            f"{n_periods} periods asked, {n_found} found: {n_periods - n_found} "
            + "forced or extreme day(s) were already representative days"
        )


def add_forced_days(
    representative_of: dict[str, str],
    features: pd.DataFrame,
    forced_days: list[str],
) -> dict[str, str]:
    """
    Add forced days to a clustering, as tsam's `_addExtremePeriods` does for
    `addManual` with `extremePeriodMethod="new_cluster_center"`.

    tsam clusters first and adds these days afterwards, and its cluster centres
    are then the scaled features of the representative days (it rescales them
    later), so this gives tsam's result from the stored clustering. tsam's quirks
    are kept:

    - a day that is already a representative is skipped (one period fewer);
    - each day moves to the last forced day it is closer to than to its
      representative, not to the closest one.

    Parameters
    ----------
    representative_of
        Season -> the season that represents it, before adding the days.
    features
        The clustered features as tsam scaled them, indexed by season and hour.
    forced_days
        Seasons to add, in order.

    Examples
    --------
    >>> features = pd.DataFrame(
    ...     {"x": [0.0, 0.0, 0.1, 0.1, 0.8, 0.8, 1.0, 0.9]},
    ...     index=pd.MultiIndex.from_product(
    ...         [["D001", "D002", "D003", "D004"], [0, 1]], names=["season", "hour"]
    ...     ),
    ... )
    >>> base = {"D001": "D002", "D002": "D002", "D003": "D002", "D004": "D002"}
    >>> add_forced_days(base, features, ["D004"])
    {'D001': 'D002', 'D002': 'D002', 'D003': 'D004', 'D004': 'D004'}
    """
    unknown = sorted(set(forced_days) - set(representative_of))
    if unknown:
        raise ValueError(f"Forced days not in the clustering: {unknown}")

    # One row per day, columns (feature, hour) in tsam's order
    profiles = features.unstack("hour")
    centres = [
        profiles.loc[r].tolist() for r in sorted(set(representative_of.values()))
    ]
    # tsam skips days already added and days whose profile is a centre's
    added: list[str] = []
    for day in forced_days:
        if day not in added and profiles.loc[day].tolist() not in centres:
            added.append(day)

    def distance(a: str, b: str) -> float:
        # tsam's arithmetic: Python's sum over the squared differences
        return sum((profiles.loc[a].to_numpy() - profiles.loc[b].to_numpy()) ** 2)

    new_representative_of = dict(representative_of)
    for day, representative in representative_of.items():
        to_representative = distance(day, representative)
        for forced in added:
            # An added day never moves to another added day
            if day in added and day != forced:
                continue
            if distance(day, forced) < to_representative:
                new_representative_of[day] = forced
    return new_representative_of

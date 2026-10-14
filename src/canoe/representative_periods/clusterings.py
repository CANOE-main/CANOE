"""
Where a clustering comes from: one variant per way of producing clusterings.

Each variant identifies a clustering, knows how to load its
`RepresentativeSeasonMapping` and has its own metadata (how the clustering was
made). `Clustering` is the tagged union of the variants, dispatched on `kind`; to
add a methodology, add a variant and extend the union.
"""

import tomllib
from datetime import datetime
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from canoe.representative_periods.mapping import RepresentativeSeasonMapping


class PCAGroup(BaseModel):
    """Series reduced together to their principal components."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    name: str
    """Prefix of the components (`<name>_pc1`, ...)."""
    columns: list[str]
    """Series of the group."""
    n_components: int
    """Number of principal components kept."""
    scale: bool
    """Whether each series is scaled to unit variance before the PCA."""


class GenerationInfo(BaseModel):
    """What a collection was generated with, written by the script that made it."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    created: datetime
    """When the collection was generated."""
    script: str
    """Script that generated it, relative to the repository root."""
    canoe_commit: str
    """Commit of the repository when it was generated."""
    canoe_dirty: bool
    """Whether the working tree had uncommitted changes."""
    tsam_version: str
    """Installed tsam version."""
    features_sha256: str
    """Hash of the feature matrix that was clustered."""
    assignments_sha256: str
    """Hash of `assignments.csv`, to detect edits by hand."""


class TsamCollectionMetadata(BaseModel):
    """Contents of the `clustering.toml` of a tsam collection."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    kind: Literal["tsam_collection"]
    """The variant the collection belongs to."""
    description: str
    """What the collection is, in a few words."""
    time_series: str
    """Source of the time series that were clustered."""
    series: list[str]
    """Series loaded for the clustering."""
    pca_groups: list[PCAGroup]
    """Principal component groups; empty if the series were clustered directly."""
    clustered_features: list[str]
    """Columns tsam actually clustered (the components, with a PCA)."""
    method: str
    """tsam clustering method (e.g. `hierarchical`)."""
    solver: str
    """Solver given to tsam (only used by some methods)."""
    hours_per_period: int
    """Hours in each period (24: periods are days)."""
    season_labels: str
    """How a day of the time series is labelled as a season of the database."""
    n_periods: list[int]
    """Numbers of periods in the collection (the columns of `assignments.csv`)."""
    generated: GenerationInfo
    """What the collection was generated with."""


class TsamCollection(BaseModel):
    """
    A clustering precomputed with tsam, from a collection with one clustering for
    each number of periods.

    A collection is a folder with:

    - `assignments.csv`: a `season` column and one column per number of periods,
      whose cells are the season representing the season of the row;
    - `clustering.toml`: its metadata (`TsamCollectionMetadata`);
    - `accuracy.csv`: tsam's accuracy indicators for each number of periods.
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
    """Number of representative periods (a column of `assignments.csv`)."""

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
        """The mapping for `n_periods`, from `assignments.csv`."""
        path = self.folder().joinpath("assignments.csv")
        with path.open("rb") as f:
            table = pd.read_csv(f, index_col="season", dtype=str)
        column = str(self.n_periods)
        if column not in table.columns:
            raise ValueError(
                f"{path} has no clustering for {self.n_periods} periods "
                + f"(columns {table.columns[0]} to {table.columns[-1]})"
            )
        representative_of = table[column].to_dict()
        missing = [s for s, r in representative_of.items() if pd.isna(r)]
        if missing:
            raise ValueError(
                f"{path}, column {column}: no representative for {missing}"
            )
        return RepresentativeSeasonMapping(
            representative_of={str(s): str(r) for s, r in representative_of.items()}
        )

    def load_metadata(self) -> TsamCollectionMetadata:
        """The metadata of the collection, from `clustering.toml`."""
        with self.folder().joinpath("clustering.toml").open("rb") as f:
            return TsamCollectionMetadata.model_validate(tomllib.load(f))


# Add new variants here, e.g. a single mapping file made by another method
Clustering = Annotated[TsamCollection, Field(discriminator="kind")]

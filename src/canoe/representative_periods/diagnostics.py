"""What a clustering did to the original series, to judge it by."""

from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict


class ClusteringDiagnostics(BaseModel):
    """
    The original series of a clustering, as recreated from the representative days,
    and their duration curves, all on the original series (columns are series
    names).
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        frozen=True, use_attribute_docstrings=True, arbitrary_types_allowed=True
    )

    accuracy: pd.DataFrame
    """Accuracy per original series: RMSE, RMSE_duration, MAE and the RMSEs scaled by
    the range of the series (see `compute.clustering_accuracy`)."""
    original: pd.DataFrame
    """Original series, indexed by season and hour."""
    recreated: pd.DataFrame
    """Each day replaced by its representative day, same index as `original`."""
    original_duration: pd.DataFrame
    """Original series sorted in descending order, indexed by rank."""
    recreated_duration: pd.DataFrame
    """Recreated series sorted in descending order, indexed by rank."""

    def save(self, directory: Path) -> None:
        """
        Write `accuracy.csv` and the plots (`series.png`, `duration.png`) to
        `directory`. Plotting needs matplotlib.
        """
        directory.mkdir(parents=True, exist_ok=True)
        self.accuracy.to_csv(directory / "accuracy.csv")
        _plot(self.original, self.recreated, "Original and recreated series",
              directory / "series.png")
        _plot(self.original_duration, self.recreated_duration, "Duration curves",
              directory / "duration.png")
        logger.info(f"Wrote the clustering diagnostics to {directory}")


class TsamDiagnostics(ClusteringDiagnostics):
    """Diagnostics of a `TsamClustering`, which can cluster principal components."""

    components: pd.DataFrame | None = None
    """Principal components (`pc1`, ...), indexed by season and hour; None without PCA."""

    def save(self, directory: Path) -> None:
        """As `ClusteringDiagnostics.save`, plus `components.png` with PCA."""
        super().save(directory)
        if self.components is not None:
            _plot(self.components, None, "Principal components",
                  directory / "components.png")


def _plot(
    base: pd.DataFrame, overlay: pd.DataFrame | None, title: str, path: Path
) -> None:
    """One subplot per column of `base`, with `overlay` drawn on top if given."""
    import matplotlib.pyplot as plt

    n_cols = 3
    n_rows = -(-len(base.columns) // n_cols)
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(6 * n_cols, 2.5 * n_rows), squeeze=False
    )
    for ax, name in zip(axes.flat, base.columns):
        ax.plot(base[name].to_numpy(), lw=0.8, label="original")
        if overlay is not None:
            ax.plot(overlay[name].to_numpy(), lw=0.8, alpha=0.8, label="recreated")
        ax.set_title(str(name), fontsize=8)
    for ax in axes.flat[len(base.columns) :]:
        ax.set_visible(False)
    if overlay is not None:
        axes.flat[0].legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)

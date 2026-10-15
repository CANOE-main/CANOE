"""
Computing a clustering of days from time series, with tsam (no database involved).

The steps of `clusterings.TsamClustering.mapping`: find the series in a folder,
select them, load them, keep the whole days of a year, reduce them with PCA, find
the extreme days and cluster the days.
"""

import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import tsam.timeseriesaggregation as tsam
from loguru import logger

ClusterMethod = Literal["hierarchical", "k_means", "k_medoids", "adjacent_periods"]
"""tsam clustering methods that can represent each cluster by its medoid day."""


def find_series(data_dir: Path) -> dict[str, Path]:
    """
    Every series of `data_dir`: its name (the file name without `.csv`) -> its file,
    relative to `data_dir`, at any depth.
    """
    files: dict[str, Path] = {}
    for path in sorted(data_dir.rglob("*.csv")):
        relative = path.relative_to(data_dir)
        if path.stem in files:
            raise ValueError(
                f"Two series named {path.stem!r} in {data_dir}: "
                + f"{files[path.stem]} and {relative}"
            )
        files[path.stem] = relative
    if not files:
        raise ValueError(f"No CSV files in {data_dir}")
    return files


def select_series(
    files: dict[str, Path], include: list[str] | None, exclude: list[str] | None
) -> list[str]:
    """
    The series whose path (relative, without `.csv`) matches a pattern of `include`,
    or else matches no pattern of `exclude`; all of them if neither is given.
    A pattern that matches no series raises (likely a typo).

    Examples
    --------
    >>> files = {
    ...     "on_temperature": Path("on/on_temperature.csv"),
    ...     "on_humidity": Path("on/on_humidity.csv"),
    ...     "load": Path("ontario/load.csv"),
    ... }
    >>> select_series(files, ["*_temperature"], None)
    ['on_temperature']
    >>> select_series(files, None, ["ontario/*"])
    ['on_temperature', 'on_humidity']
    """
    keys = {name: path.with_suffix("").as_posix() for name, path in files.items()}
    patterns = include if include is not None else exclude
    if patterns is None:
        return list(files)
    unmatched = [
        p for p in patterns if not any(fnmatchcase(k, p) for k in keys.values())
    ]
    if unmatched:
        raise ValueError(f"Patterns that match no series: {unmatched}")
    matched = [n for n, k in keys.items() if any(fnmatchcase(k, p) for p in patterns)]
    selected = (
        matched if include is not None else [n for n in files if n not in matched]
    )
    if not selected:
        raise ValueError("No series selected")
    return selected


def load_series(
    data_dir: Path, files: dict[str, Path], names: list[str]
) -> pd.DataFrame:
    """
    The series `names`, one column each, indexed by time in EST (the time of the
    database). Each file has a `time` column, with UTC offsets, and one column of
    values.
    """
    columns: dict[str, pd.Series] = {}
    for name in names:
        path = data_dir / files[name]
        table = pd.read_csv(path, encoding="utf-8-sig")
        if "time" not in table.columns or len(table.columns) != 2:
            raise ValueError(
                f"{path}: expected a `time` column and one column of values, "
                + f"found {list(table.columns)}"
            )
        times = table["time"].astype(str)
        no_offset = [t for t in times if not re.search(r"(Z|[+-]\d\d:?\d\d)$", t)]
        if no_offset:
            raise ValueError(
                f"{path}: times without a UTC offset, e.g. {no_offset[0]!r}"
            )
        index = pd.DatetimeIndex(pd.to_datetime(times, utc=True, format="ISO8601"))
        if index.has_duplicates:
            raise ValueError(f"{path}: repeated times")
        values = table.drop(columns="time").iloc[:, 0].astype(float).to_numpy()
        columns[name] = pd.Series(values, index=index.tz_convert("EST"))
    return pd.DataFrame(columns)


def daily_table(series: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    The whole days of `year` in `series`, indexed by season (`Dnnn`, day nnn of the
    year) and hour. Days without a value of every series at every hour from midnight
    are left out (logged).

    Examples
    --------
    >>> times = pd.date_range("2018-01-01 05:00", periods=72, freq="h", tz="UTC")
    >>> series = pd.DataFrame({"x": range(72)}, index=times.tz_convert("EST"))
    >>> table = daily_table(series.iloc[:-1], 2018)
    >>> table.index.unique("season").tolist(), table.shape
    (['D001', 'D002'], (48, 1))
    """
    times = pd.Series(pd.to_datetime(series.index))
    dates, hours, minutes = times.dt.date, times.dt.hour, times.dt.minute
    days: dict[str, pd.DataFrame] = {}
    left_out: list[str] = []
    for date in sorted(set(dates[(times.dt.year == year).to_numpy()])):
        on_date = (dates == date).to_numpy()
        day = series.loc[on_date]
        season = f"D{pd.Timestamp(date).dayofyear:03d}"
        whole = list(hours[on_date]) == list(range(24)) and bool(
            (minutes[on_date] == 0).all()
        )
        if whole and not day.isna().to_numpy().any():
            days[season] = day.set_axis(pd.RangeIndex(24, name="hour"))
        else:
            left_out.append(season)
    if not days:
        raise ValueError(f"No whole day of {year} in the series")
    if left_out:
        logger.info(
            f"Days of {year} left out (not covered by every series): {left_out}"
        )
    return pd.concat(days, names=["season", "hour"])


def principal_components(table: pd.DataFrame, n_components: int) -> pd.DataFrame:
    """
    Scores of the first `n_components` principal components of the standardised
    columns of `table` (`pc1`, ...), each with the sign that makes the sum of its
    loadings positive. The arithmetic of the old module's `pca.py`.
    """
    if n_components > table.shape[1]:
        raise ValueError(
            f"{n_components} principal components of {table.shape[1]} series"
        )
    std = table.std(axis=0, ddof=0).replace(0.0, 1.0)
    standardised = (table - table.mean(axis=0)) / std
    u, s, vt = np.linalg.svd(standardised.to_numpy(), full_matrices=False)
    scores = u[:, :n_components] * s[:n_components]
    for i in range(n_components):
        if np.nansum(vt[i]) < 0:
            scores[:, i] *= -1
    return pd.DataFrame(
        scores,
        index=table.index,
        columns=[f"pc{i + 1}" for i in range(n_components)],
    )


def extreme_days(
    table: pd.DataFrame,
    max_peak: list[str],
    min_peak: list[str],
    max_mean: list[str],
    min_mean: list[str],
) -> list[str]:
    """
    The day of each extreme, in order: the days with the highest hourly value of
    each series of `max_peak`, the lowest of `min_peak`, the highest daily mean of
    `max_mean` and the lowest of `min_mean` (the first day on ties).
    """
    # One row per day, columns (series, hour)
    days = table.unstack("hour")
    return (
        [str(days[name].max(axis=1).idxmax()) for name in max_peak]
        + [str(days[name].min(axis=1).idxmin()) for name in min_peak]
        + [str(days[name].mean(axis=1).idxmax()) for name in max_mean]
        + [str(days[name].mean(axis=1).idxmin()) for name in min_mean]
    )


def cluster_days(
    features: pd.DataFrame,
    n_clusters: int,
    method: ClusterMethod,
    added_days: list[str],
) -> dict[str, str]:
    """
    The season that represents each day of `features` (indexed by season and hour):
    tsam clusters the days into `n_clusters`, each represented by its medoid day,
    then adds `added_days`, each taking the days closer to it than to their
    representative (`extremePeriodMethod="new_cluster_center"`). tsam skips an added
    day that is already a representative.
    """
    seasons = list(features.index.unique("season"))
    aggregation = tsam.TimeSeriesAggregation(
        features.reset_index(drop=True),
        noTypicalPeriods=n_clusters,
        hoursPerPeriod=24,
        clusterMethod=method,
        representationMethod="medoidRepresentation",
        extremePeriodMethod="new_cluster_center",
        addManual=[seasons.index(day) for day in added_days],
        resolution=1,
    )
    aggregation.createTypicalPeriods()
    centres = aggregation.clusterCenterIndices
    assert centres is not None, "tsam computed no medoids"
    representatives = [int(c) for c in centres] + [
        int(p["stepNo"]) for p in aggregation.extremePeriods.values()
    ]
    return {
        seasons[day]: seasons[representatives[cluster]]
        for day, cluster in enumerate(aggregation.clusterOrder)
    }

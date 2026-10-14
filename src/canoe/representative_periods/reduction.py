"""
The values of the reduced database, the same in every schema version: the kept
seasons and their share of the year, their chronological sequence, and the demand
distribution and demands that go with them. Tidy frames in, tidy frames out; the
`_reduce_v*` functions of `build` read and write them.
"""

from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd
from loguru import logger

from canoe.representative_periods.mapping import RepresentativeSeasonMapping


def representative_seasons(
    mapping: RepresentativeSeasonMapping, seasons: pd.DataFrame
) -> pd.DataFrame:
    """
    The representative seasons and their share of the year.

    Parameters
    ----------
    mapping
        The clustering.
    seasons
        Every season of the database in chronological order, with its share of the
        year: columns `season` and `segment_fraction`.

    Returns
    -------
    pd.DataFrame
        One row per representative, in chronological order:

        - `season`;
        - `represented`: number of seasons it stands for (itself included);
        - `segment_fraction`: its share of the year, `represented` over the number
          of seasons the mapping covers (seasons it leaves out are spread over the
          representatives);
        - `weight`: `segment_fraction` over its own share in the input database,
          i.e. how many of its own lengths of time it stands for.

    Examples
    --------
    >>> mapping = RepresentativeSeasonMapping(
    ...     representative_of={"D001": "D002", "D002": "D002", "D003": "D003"}
    ... )
    >>> seasons = pd.DataFrame(
    ...     {"season": ["D001", "D002", "D003", "D004"], "segment_fraction": 0.25}
    ... )
    >>> representative_seasons(mapping, seasons)
      season  represented  segment_fraction    weight
    0   D002            2          0.666667  2.666667
    1   D003            1          0.333333  1.333333
    """
    represented = mapping.weights(seasons["season"].tolist())
    input_fraction = dict(zip(seasons["season"], seasons["segment_fraction"]))
    n_mapped = len(mapping.representative_of)
    return pd.DataFrame(
        {
            "season": list(represented),
            "represented": list(represented.values()),
            "segment_fraction": [n / n_mapped for n in represented.values()],
            "weight": [
                n / n_mapped / input_fraction[s] for s, n in represented.items()
            ],
        }
    )


def sequential_seasons(
    mapping: RepresentativeSeasonMapping, seasons: pd.DataFrame
) -> pd.DataFrame:
    """
    The year rebuilt from the representatives, for `time_season_sequential`: the
    seasons in chronological order, each replaced by its representative, with
    consecutive seasons of the same representative merged into one.

    Parameters
    ----------
    mapping
        The clustering.
    seasons
        Every season of the database in chronological order: column `season`.
        Seasons the mapping leaves out are skipped.

    Returns
    -------
    pd.DataFrame
        One row per run: `seas_seq` (`S0`, `S1`, ..., zero-padded to the same
        width), `season` (the representative) and `segment_fraction` (length of the
        run over the number of seasons the mapping covers).

    Examples
    --------
    >>> mapping = RepresentativeSeasonMapping(
    ...     representative_of={"D001": "D002", "D002": "D002", "D003": "D003"}
    ... )
    >>> sequential_seasons(mapping, pd.DataFrame({"season": ["D001", "D002", "D003"]}))
      seas_seq season  segment_fraction
    0       S0   D002          0.666667
    1       S1   D003          0.333333
    """
    chronological = [
        mapping.representative_of[s]
        for s in seasons["season"]
        if s in mapping.representative_of
    ]
    runs: list[list[str | int]] = []
    for representative in chronological:
        if runs and runs[-1][0] == representative:
            runs[-1][1] = int(runs[-1][1]) + 1
        else:
            runs.append([representative, 1])
    width = len(str(len(runs)))
    return pd.DataFrame(
        {
            "seas_seq": [f"S{i:0{width}d}" for i in range(len(runs))],
            "season": [str(rep) for rep, _ in runs],
            "segment_fraction": [int(n) / len(chronological) for _, n in runs],
        }
    )


def reweight_demand_distribution(
    dsd: pd.DataFrame, kept: pd.DataFrame, threshold: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    The demand distribution over the representative seasons, and how much of each
    demand they keep.

    For each region, period and demand: each value is weighted by how many of its
    own season's lengths the season stands for (`weight`), the smallest weighted
    values whose cumulative share stays below `threshold` are set to zero, and the
    rest is normalised to sum to 1. If nothing is left (no demand on any
    representative), the distribution is spread equally over its rows.

    Parameters
    ----------
    dsd
        Distribution rows of the representative seasons: columns `region`,
        `period`, `season`, `tod`, `demand_name` and `dsd`.
    kept
        The representatives, from `representative_seasons` (`season`, `weight`).
    threshold
        Share of each distribution set to zero.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        The new distribution (same columns as `dsd`), and per `region`, `period` and
        `demand_name` the `scale`: the share of the annual demand the representative
        seasons hold with the hourly values of the input (1 if spread equally).
        Multiplying the annual demand by it keeps the hourly values.

    Examples
    --------
    One demand over two representatives, the first standing for three seasons:

    >>> kept = pd.DataFrame({"season": ["D001", "D002"], "weight": [3.0, 1.0]})
    >>> dsd = pd.DataFrame(
    ...     {
    ...         "region": "ON",
    ...         "period": 2025,
    ...         "season": ["D001", "D001", "D002", "D002"],
    ...         "tod": ["H01", "H02", "H01", "H02"],
    ...         "demand_name": "D",
    ...         "dsd": [0.1, 0.2, 0.001, 0.3],
    ...     }
    ... )
    >>> new_dsd, scale = reweight_demand_distribution(dsd, kept, threshold=0.01)
    >>> new_dsd["dsd"].round(4).tolist()
    [0.25, 0.5, 0.0, 0.25]
    >>> scale["scale"].round(4).tolist()
    [1.2]
    """
    keys = ["region", "period", "demand_name"]
    weights = dict(zip(kept["season"], kept["weight"]))
    weighted = dsd.assign(dsd=dsd["dsd"] * [weights[s] for s in dsd["season"]])

    new_values: list[pd.Series] = []
    scales: list[tuple[str, int, str, float]] = []
    for key, rows in weighted.groupby(keys, sort=False):
        region, period, demand = cast(tuple[str, int, str], key)
        values, scale = threshold_and_normalise(
            rows["dsd"].to_numpy(dtype=float), threshold
        )
        if scale == 0:
            # Nothing on the representatives: spread equally, demand untouched
            logger.warning(
                f"No demand distribution of {demand} ({region}, {period}) on the "
                + "representative seasons: spread equally (choose other representatives)"
            )
            values, scale = np.full(len(values), 1 / len(values)), 1.0
        new_values.append(pd.Series(values, index=rows.index))
        scales.append((str(region), int(period), str(demand), scale))

    new_dsd = dsd.assign(dsd=pd.concat(new_values))
    return new_dsd, pd.DataFrame(scales, columns=[*keys, "scale"])


def threshold_and_normalise(
    values: npt.NDArray[np.float64], threshold: float
) -> tuple[npt.NDArray[np.float64], float]:
    """
    Set to zero the smallest values whose cumulative share stays below `threshold`
    (values tied with the last of them too), then normalise to sum to 1. The largest
    value is never dropped, so a flat distribution is left whole.

    Returns the normalised values and the sum they were divided by (0, with the
    values unchanged, if they sum to 0).

    Examples
    --------
    >>> values, total = threshold_and_normalise(np.array([0.3, 0.6, 0.001, 0.3]), 0.01)
    >>> values.round(4).tolist(), round(total, 4)
    ([0.25, 0.5, 0.0, 0.25], 1.2)
    >>> threshold_and_normalise(np.array([1.0, 1.0]), 0.6)[0].tolist()
    [0.5, 0.5]
    """
    total = float(values.sum())
    if total == 0:
        return values, 0.0
    ordered = np.sort(values)
    below = ordered[np.cumsum(ordered) / total < threshold]
    if below.size:
        cutoff = below.max() + 1e-12  # buffer for floating point
        if cutoff < values.max():
            values = np.where(values < cutoff, 0.0, values)
    kept_total = float(values.sum())
    return values / kept_total, kept_total

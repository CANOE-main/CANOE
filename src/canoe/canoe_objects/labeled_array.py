from collections.abc import Sequence
from itertools import product
from typing import Any, Self

import numpy as np
import pandas as pd


class LabeledArray:
    """
    A minimal N-dimensional labeled array, similar in spirit to xarray.

    Parameters
    ----------
    coords : dict[str, list]
        Maps each dimension name to its ordered list of coordinate values.
    fill : float
        Default value for unset cells.

    Notes
    -----
    Internally backed by a single dense np.ndarray of shape
    (len(coords[dim0]), len(coords[dim1]), ...). Dimension order is the
    insertion order of the `coords` dict.
    """

    def __init__(self, coords: dict[str, list[Any]], fill: float = np.nan):
        self.dims: list[str] = list(coords.keys())
        self.coords: dict[str, list[Any]] = {d: list(v) for d, v in coords.items()}
        self._idx: dict[str, dict[Any, int]] = {
            d: {v: i for i, v in enumerate(vals)} for d, vals in self.coords.items()
        }
        self.shape: tuple[int, ...] = tuple(len(v) for v in self.coords.values())
        self.data: np.ndarray = np.full(self.shape, fill, dtype=float)

    def _index_tuple(
        self, kwargs: dict[str, Any], allow_partial: bool = True
    ) -> tuple[Any, ...]:
        idx: list[Any] = []
        for d in self.dims:
            if d in kwargs:
                idx.append(self._idx[d][kwargs[d]])
            elif allow_partial:
                idx.append(slice(None))
            else:
                raise KeyError(f"missing coordinate for dim '{d}'")
        return tuple(idx)

    def set(self, value: Any, **coord_kwargs: Any):
        """Set one cell (all dims given) or broadcast a scalar over omitted dims."""
        self.data[self._index_tuple(coord_kwargs)] = value

    def set_block(
        self,
        array: np.ndarray | list[Any],
        dims: Sequence[str],
        **fixed_dims: dict[str, Any],
    ):
        """
        Assign an array to a sub-block.

        Parameters
        ----------
        array : array-like
            Data to write. Its axes correspond to `dims`, in that order.
        dims : sequence[str]
            Names of `array`'s axes, e.g. ("region", "time"). Must equal
            the set of dims NOT given in `fixed_dims`.
        **fixed_dims
            Coordinate values for the dims held fixed, e.g. period="2024".
        """
        remaining = [d for d in self.dims if d not in fixed_dims]

        if not set(dims) <= set(remaining):
            raise ValueError(f"dims {dims} not among remaining dims {remaining}")
        if len(set(dims)) != len(dims):
            raise ValueError(f"dims has duplicates: {dims}")

        array = np.asarray(array, dtype=float)
        expected_shape = tuple(len(self.coords[d]) for d in dims)
        if array.shape != expected_shape:
            raise ValueError(
                f"array shape {array.shape} does not match "
                + f"expected shape {expected_shape} for dims {dims}"
            )

        # Order array axes to match their relative order in `remaining`.
        ordered_named = [d for d in remaining if d in dims]
        perm = [dims.index(d) for d in ordered_named]
        array = np.transpose(array, perm)

        # Insert a size-1 axis for each remaining dim not named in `dims`.
        for pos, d in enumerate(remaining):
            if d not in dims:
                array = np.expand_dims(array, axis=pos)

        idx = self._index_tuple(fixed_dims)
        self.data[idx] = array

    def get(self, **coord_kwargs: Any) -> np.ndarray:
        return self.data[self._index_tuple(coord_kwargs, allow_partial=True)]

    def to_records(self) -> list[dict[str, Any]]:
        """Flatten to a list of dicts: one dict per dim value combination."""
        records: list[dict[str, Any]] = []
        for combo in product(*(self.coords[d] for d in self.dims)):
            idx = tuple(self._idx[d][v] for d, v in zip(self.dims, combo))
            rec = dict(zip(self.dims, combo))
            rec["value"] = self.data[idx]
            records.append(rec)
        return records

    def fill_from_df(
        self,
        df: pd.DataFrame | pd.Series,
        value_col: str = "value",
        agg: str = "sum",
        dims: Sequence[str] | None = None,
        fill: float = np.nan,
    ) -> Self:
        """
        Fill this array's data from a long-format DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain one column per dim used, plus `value_col`.
        value_col : str
            Column holding the values to place in the array.
        agg : str
            Aggregation applied when a coordinate combination appears more
            than once (passed to `groupby(...).agg`).
        dims : sequence[str], optional
            Dims to fill, in the order to read the block. Default: all of
            self.dims, in that order.
        fill : float
            Value used for coordinate combinations absent from `df`.
            Default NaN.

        Notes
        -----
        Plain overwrite. Coordinate combinations absent from `df` are set
        to `fill`. Coordinate values in `df` not present in `self.coords`
        are dropped silently.
        """
        if dims is None:
            dims = self.dims
        dims = list(dims)

        missing = [d for d in dims if d not in df.columns]
        if missing:
            raise ValueError(f"df is missing columns for dims: {missing}")
        if value_col not in df.columns:
            raise ValueError(f"df is missing value column '{value_col}'")

        grouped = df.groupby(dims)[value_col].agg(agg)

        full_index = pd.MultiIndex.from_product(
            [self.coords[d] for d in dims], names=dims
        )
        shape = tuple(len(self.coords[d]) for d in dims)
        block = grouped.reindex(full_index, fill_value=fill).values.reshape(shape)  # pyright: ignore[reportAttributeAccessIssue]

        self.set_block(block, dims=tuple(dims))
        return self

    @classmethod
    def from_df(
        cls,
        df: pd.DataFrame,
        dims: Sequence[str],
        value_col: str = "value",
        agg: str = "sum",
        fill: float = np.nan,
    ) -> "LabeledArray":
        """
        Build a LabeledArray from a long-format DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain one column per name in `dims`, plus `value_col`.
        dims : sequence[str]
            Dimension names, in the desired axis order. Each must be a
            column in `df`.
        value_col : str
            Column holding the values to place in the array.
        agg : str
            Aggregation applied when a coordinate combination appears more
            than once.
        fill : float
            Value for coordinate combinations missing from `df`.

        Returns
        -------
        LabeledArray
        """
        missing = [d for d in dims if d not in df.columns]
        if missing:
            raise ValueError(f"df is missing columns for dims: {missing}")
        if value_col not in df.columns:
            raise ValueError(f"df is missing value column '{value_col}'")

        coords = {d: sorted(df[d].unique()) for d in dims}
        arr = cls(coords, fill=fill)
        arr.fill_from_df(df, value_col=value_col, agg=agg, dims=dims, fill=fill)
        return arr

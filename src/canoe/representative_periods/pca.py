"""pca_utils.py
Utilities for computing principal components from groups of time series in a DataFrame.

Assumptions (per user request):
- Group columns are provided as **string column names** (no integer positions).
- **No imputation** is performed. If NaNs exist in a group's columns, a ValueError is raised.

Example config:
----------------
config = {
    "groups": [
        {
            "name": "grp123",
            "columns": ["ts1", "ts2", "ts3"],
            "n_components": 2,
            "scale": True   # optional (default True)
        },
        {
            "name": "single",
            "columns": ["ts4"],
            "n_components": 1
        }
    ]
}

Usage:
------
from pca_utils import get_principal_components
pcs_df = get_principal_components(df, config)
"""

from typing import Dict, List
import numpy as np
import pandas as pd


def standardise(X: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Center (and optionally scale) the columns of X.

    Returns standardised frame, means, stds used.
    stds for constant columns are set to 1 to avoid division by zero.
    """
    mu = X.mean(axis=0)
    Xc = X - mu

    std = X.std(axis=0, ddof=0)
    std_replaced = std.replace(0.0, 1.0)  # avoid division by zero
    return Xc / std_replaced


def _pca_scores_via_svd(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute first k principal component scores and loadings via SVD.

    X should already be centered (and scaled if desired).
    Returns (scores, loadings) where:
      - scores shape: (n_samples, k)  = U[:, :k] * S[:k]
      - loadings shape: (k, n_features) = Vt[:k, :]
    Also flips signs to make each component's loadings sum positive (deterministic sign).
    """
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    k = max(0, min(k, U.shape[1]))
    if k == 0:
        return np.zeros((X.shape[0], 0)), np.zeros((0, X.shape[1]))
    scores = U[:, :k] * S[:k]
    loadings = Vt[:k, :]
    # Deterministic sign: flip so sum of loadings for each component is >= 0
    for i in range(k):
        if np.nansum(loadings[i]) < 0:
            loadings[i] *= -1
            scores[:, i] *= -1
    return scores, loadings


def get_principal_components(df: pd.DataFrame, groups: list[Dict]) -> pd.DataFrame:
    """Compute principal components for groups of time series in `df`.

    Parameters
    ----------
    df : pd.DataFrame
        A DataFrame indexed by time (or any index) with time series columns.
    config : dict
        Configuration dict with a "groups" key, a list of group configs.
        Each group config is a dict with keys:
          - name (str, optional): Used to prefix output columns. If omitted,
                                  a default name like "group0" is used.
          - columns (List[str]): Column names in `df` (strings only).
          - n_components (int): Number of principal components to return for this group.
          - scale (bool, optional): If True (default), z-score each series within the group
                                    prior to PCA. If False, only mean-centers.

    Returns
    -------
    pd.DataFrame
        DataFrame of principal component scores with the same index as `df`.
        Columns are named "{group_name}_pc{1..k}".

    Notes
    -----
    - No imputation is performed. If NaNs exist in a group's columns, a ValueError is raised.
    - All specified columns must exist and be numeric; otherwise a ValueError is raised.
    - If `n_components` exceeds the number of available numeric columns, it is clipped.
    """

    if not isinstance(groups, list) or len(groups) == 0:
        raise ValueError("config['groups'] must be a non-empty list")

    out_parts: List[pd.DataFrame] = []

    for gi, g in enumerate(groups):
        name = g.get("name", f"group{gi}")
        cols = g.get("columns", [])
        k = int(g.get("n_components", 0))
        if k <= 0:
            continue  # nothing to do

        # Validate columns are strings and exist
        if not all(isinstance(c, str) for c in cols):
            raise ValueError(f"Group '{name}': all 'columns' must be string names.")
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"Group '{name}': columns not found in df: {missing}")

        # Ensure all are numeric
        non_numeric = [c for c in cols if not pd.api.types.is_numeric_dtype(df[c])]
        if non_numeric:
            raise ValueError(f"Group '{name}': non-numeric columns: {non_numeric}")

        X = df[cols].copy().interpolate("linear")

        # Check for NaNs
        if X.isna().any().any():
            na_cols = [c for c in cols if X[c].isna().any()]
            raise ValueError(
                f"Group '{name}': NaNs present in columns {na_cols}. "
                "Please drop or impute NaNs before calling get_principal_components."
            )

        # Standardise (center and optionally scale)
        X_std = standardise(X)

        # PCA via SVD
        k_eff = int(np.clip(k, 0, X_std.shape[1]))
        scores, loadings = _pca_scores_via_svd(X_std.to_numpy(), k_eff)

        # Create output columns
        col_names = [f"{name}_pc{i + 1}" for i in range(k_eff)]
        pcs_df = pd.DataFrame(scores, index=df.index, columns=col_names)
        out_parts.append(pcs_df)

    if not out_parts:
        # Return empty frame with same index if nothing computed
        print(f"Got no PCs for {name}")
        return pd.DataFrame(index=df.index)

    return pd.concat(out_parts, axis=1)

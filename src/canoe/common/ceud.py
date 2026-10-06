"""
Layout of the NRCan Comprehensive Energy Use Database (CEUD) tables, shared by the
sectors that read them.

A CEUD table has a label column and one column per year. The rows read here are the
total energy use and two blocks of energy sources, each under its header row:

```
Total <...> Energy Use (PJ)
Energy Use by Energy Source (PJ)
<source>                          <- one row per energy source
...
Shares (%)
<source>                          <- the same sources, percent of the total
...
```

Each sector's loaders read the cached tables (they know the dataset names and the
energy sources of their tables) and parse them with `parse_ceud_energy_use`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from canoe.common.fuels import CANOEFuel

_ENERGY_USE_HEADER = "Energy Use by Energy Source (PJ)"
_SHARES_HEADER = "Shares (%)"
_LABEL_COLUMN = "Unnamed: 0"
# Values NRCan publishes instead of a number (not available, confidential, nil)
_MISSING_MARKERS = {"n.a.", "X", "x", "..", "–", "-"}


@dataclass(frozen=True)
class CEUDEnergyUse:
    """
    Energy use of one NRCan CEUD table in one year.

    Parameters
    ----------
    total : float
        Total energy use (PJ), all sources.
    by_source : pd.DataFrame
        One row per energy source (index: NRCan label) with columns `fuel`
        (`CANOEFuel`, missing for sources with no CANOE fuel), `energy_use` (PJ) and
        `share` (percent of the total, as published). Values NRCan does not publish
        are NaN.
    """

    total: float
    by_source: pd.DataFrame


def parse_ceud_energy_use(
    table: pd.DataFrame,
    dataset: str,
    data_year: int,
    total_label: str,
    sources: Mapping[str, CANOEFuel | None],
) -> CEUDEnergyUse:
    """
    Total energy use and energy use by source of a NRCan CEUD table.

    Parameters
    ----------
    table : pd.DataFrame
        The table as cached: a label column and a column per year.
    dataset : str
        Name of the cached dataset, for the error messages.
    data_year : int
        Year (column) read.
    total_label : str
        Label of the total energy use row (e.g. "Total Energy Use (PJ)").
    sources : Mapping[str, CANOEFuel | None]
        Energy sources of the table (row labels, in the table's order) -> CANOE fuel,
        or None for sources with no CANOE fuel.

    Raises
    ------
    ValueError
        If the table lacks `data_year`, an expected row, has unexpected energy
        sources or values that are neither numbers nor NRCan missing-value markers.

    Examples
    --------
    >>> table = pd.DataFrame(
    ...     {
    ...         "Unnamed: 0": [
    ...             "Total Energy Use (PJ)",
    ...             "Energy Use by Energy Source (PJ)",
    ...             "Electricity",
    ...             "Steam",
    ...             "Shares (%)",
    ...             "Electricity",
    ...             "Steam",
    ...         ],
    ...         "2022": ["8.0", "", "n.a.", "2.0", "", "n.a.", "25.0"],
    ...     }
    ... )
    >>> ceud = parse_ceud_energy_use(
    ...     table,
    ...     "example",
    ...     2022,
    ...     "Total Energy Use (PJ)",
    ...     {"Electricity": CANOEFuel.Electricity, "Steam": None},
    ... )
    >>> ceud.total
    8.0
    >>> ceud.by_source.reset_index()
            source         fuel  energy_use  share
    0  Electricity  Electricity         NaN    NaN
    1        Steam          NaN         2.0   25.0
    """
    year_column = str(data_year)
    if year_column not in table.columns:
        years = [c for c in table.columns if str(c).isdigit()]
        raise ValueError(
            f"{dataset}: year {data_year} not in the table. Years: {years}"
        )
    labels = [str(label).strip() for label in table[_LABEL_COLUMN]]
    values = table[year_column].tolist()

    def value(row: int) -> float:
        raw = values[row]
        if raw is None or str(raw).strip() in _MISSING_MARKERS:
            return np.nan
        try:
            return float(raw)
        except ValueError:
            raise ValueError(
                f"{dataset}: unexpected value {raw!r} in row {labels[row]!r}, {data_year}"
            ) from None

    def block(header: str, start: int) -> dict[str, int]:
        """Rows (label -> position) after the first `header` at or after `start`"""
        if header not in labels[start:]:
            raise ValueError(f"{dataset}: row {header!r} not found")
        first = labels.index(header, start) + 1
        rows: dict[str, int] = {}
        for position in range(first, len(labels)):
            if labels[position] not in sources:
                break
            rows[labels[position]] = position
        missing = set(sources) - set(rows)
        if missing:
            raise ValueError(
                f"{dataset}: energy sources {sorted(missing)} missing under {header!r}"
            )
        return rows

    if total_label not in labels:
        raise ValueError(f"{dataset}: row {total_label!r} not found")
    energy_use_rows = block(_ENERGY_USE_HEADER, 0)
    share_rows = block(_SHARES_HEADER, max(energy_use_rows.values()))

    by_source = pd.DataFrame(
        {
            "fuel": list(sources.values()),
            "energy_use": [value(energy_use_rows[s]) for s in sources],
            "share": [value(share_rows[s]) for s in sources],
        },
        index=pd.Index(list(sources), name="source"),
    )
    return CEUDEnergyUse(total=value(labels.index(total_label)), by_source=by_source)

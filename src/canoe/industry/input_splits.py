"""
Input splits of the industry subsector technologies: the fuel mix of each subsector
in each province, from the shares NRCan publishes in the CEUD industry tables.

Two steps:

1. `compute_ceud_shares`: the published shares, made usable (the previous module's
   algorithm). Each share is rounded to 3 decimals. If the published shares add up
   to more than 1 (rounding, e.g. 100.1%), the excess is taken off the smallest
   positive share. Sources NRCan does not publish (`n.a.`, `X`) share the rest
   evenly.
2. `compute_input_splits`: the shares of the fuels a subsector does not model (left
   out of its fuels, or "Other" with `other_fuels = "deduct"`) are spread over its
   fuels in proportion to their shares, so the splits add up to the same total.

With every fuel modelled the splits are the shares of step 1, as in the previous
module. Nothing in here touches the database.
"""

from typing import cast

import numpy as np
import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince

from .subsectors import IndustrySubsector

_KEYS = ["province", "subsector"]


def compute_ceud_shares(energy_use_by_source: pd.DataFrame) -> pd.DataFrame:
    """
    Share of each energy source in the energy use of each province and subsector.

    params:
    - energy_use_by_source: see `energy_use.compute_energy_use_by_source` (`share`
      is the fraction NRCan publishes, NaN where it does not). Not modified.

    Returns province, subsector, fuel, share (0-1, 3 decimals; each province and
    subsector adds up to at most 1)

    Examples
    --------
    >>> from canoe.common import CANOEProvince
    >>> ON, cement = CANOEProvince.ONTARIO, IndustrySubsector.Cement
    >>> df = pd.DataFrame(
    ...     {
    ...         "province": ON,
    ...         "subsector": cement,
    ...         "fuel": [CANOEFuel.Electricity, CANOEFuel.NaturalGas, CANOEFuel.Coal],
    ...         "share": [0.501, 0.499, 0.002],
    ...     }
    ... )

    The published shares add up to 1.002: the excess comes off the smallest one.

    >>> compute_ceud_shares(df)[["fuel", "share"]]
              fuel  share
    0  Electricity  0.501
    1   NaturalGas  0.499
    2         Coal  0.000

    Sources NRCan does not publish share the rest evenly:

    >>> df["share"] = [0.5, np.nan, np.nan]
    >>> compute_ceud_shares(df)[["fuel", "share"]]
              fuel  share
    0  Electricity   0.50
    1   NaturalGas   0.25
    2         Coal   0.25
    """
    frames = [
        _usable_shares(group)
        for _, group in energy_use_by_source.groupby(_KEYS, sort=False)
    ]
    return pd.concat(frames, ignore_index=True)[[*_KEYS, "fuel", "share"]]  # pyright: ignore[reportReturnType]


def _usable_shares(group: pd.DataFrame) -> pd.DataFrame:
    """`compute_ceud_shares` for the sources of one province and subsector"""
    shares = group["share"].round(3).to_numpy(dtype=float, copy=True)
    published = ~np.isnan(shares)
    total = shares[published].sum()
    if total > 1:
        positive = np.where(published & (shares > 0))[0]
        smallest = positive[np.argmin(shares[positive])]
        shares[smallest] = max(0.0, round(shares[smallest] - round(total - 1, 3), 3))
        total = shares[published].sum()
    if not published.all():
        shares[~published] = round(max(0.0, 1 - total) / (~published).sum(), 3)
    return group.assign(share=shares)


def compute_input_splits(
    shares: pd.DataFrame,
    fuels_of: dict[IndustrySubsector, list[CANOEFuel]],
    model_periods: list[int],
) -> pd.DataFrame:
    """
    Share of each modelled fuel in the inputs of each subsector technology, in every
    model period (the fuel mix of the CEUD year).

    The share of the sources a subsector does not model is spread over its fuels in
    proportion to their shares; a province where none of the subsector's fuels has
    a share gets no splits for it.

    params:
    - shares: see `compute_ceud_shares`
    - fuels_of: fuels of each subsector modelled (the technology's inputs); other
      subsectors are left out
    - model_periods: periods written

    Returns region, period, subsector, fuel, split (0-1; may be 0)

    Examples
    --------
    >>> from canoe.common import CANOEProvince
    >>> ON, cement = CANOEProvince.ONTARIO, IndustrySubsector.Cement
    >>> ELC, NG, OTH = CANOEFuel.Electricity, CANOEFuel.NaturalGas, CANOEFuel.Other
    >>> shares = pd.DataFrame(
    ...     {
    ...         "province": ON,
    ...         "subsector": cement,
    ...         "fuel": [ELC, NG, OTH],
    ...         "share": [0.2, 0.6, 0.2],
    ...     }
    ... )
    >>> compute_input_splits(shares, {cement: [ELC, NG]}, [2025])
        region  period subsector         fuel  split
    0  Ontario    2025    Cement  Electricity   0.25
    1  Ontario    2025    Cement   NaturalGas   0.75
    """
    frames: list[pd.DataFrame] = []
    for keys, group in shares.groupby(_KEYS, sort=False):
        province, subsector = cast(tuple[CANOEProvince, IndustrySubsector], keys)
        if subsector not in fuels_of:
            continue
        modelled = group.loc[group["fuel"].isin(fuels_of[subsector])]
        modelled_total = modelled["share"].sum()
        if modelled_total <= 0:
            continue
        spread = group["share"].sum() / modelled_total
        frames.append(
            pd.DataFrame(
                {
                    "region": province,
                    "subsector": subsector,
                    "fuel": modelled["fuel"].to_list(),
                    "split": (modelled["share"] * spread).to_list(),
                }
            )
        )
    columns = ["region", "period", "subsector", "fuel", "split"]
    if not frames:
        return pd.DataFrame(columns=columns)
    splits = pd.concat(frames, ignore_index=True)
    periods = pd.DataFrame({"period": model_periods})
    return splits.merge(periods, how="cross")[columns]  # pyright: ignore[reportReturnType]

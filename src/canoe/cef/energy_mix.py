"""
Demand and fuel mix of a CEF sector: the CEF end-use energy demand by province, period
and fuel becomes the sector demand (the energy of all its fuels) and the share of each
fuel in it (the input splits of the sector technology).

Fuels with a small share (below `small_share_threshold`) get a zero share, so the
model does not carry a technology input for a negligible stream; how their energy is
treated is a `SmallShareStrategy`. Nothing in here touches the database.
"""

from enum import StrEnum

import pandas as pd


class SmallShareStrategy(StrEnum):
    """
    What happens to the fuels whose share of the sector energy demand is below
    `small_share_threshold`.
    """

    ZeroSmallShares = "zero_small_shares"
    """The demand is the energy of every fuel. A fuel below the threshold in a period
    gets a zero share there, and the other shares are scaled up to add up to 1, so
    the other fuels supply its energy. A fuel below the threshold in every period of
    a province is left out of the technology there."""

    DropSmallFuels = "drop_small_fuels"
    """A fuel below the threshold (`>=` to stay) in every period of a province leaves
    the demand as well as the technology there, so its energy is not supplied.
    In each period, the other fuels whose share of the remaining demand is not above
    the threshold (`>` to stay) get a zero share and the other shares are scaled up,
    as with `zero_small_shares`. Reproduces the previous CEF module."""


def round_energy_use(energy: pd.DataFrame) -> pd.DataFrame:
    """
    Energy demand rounded to 0.01 PJ (10 TJ), as the previous CEF module did before
    computing the demand and the shares. CEF publishes four decimals; the rounding
    changes sector demands by at most 0.03 PJ and shares by at most 0.0014, well
    below the precision of the projections, and keeps the demands of the reference
    databases.

    params:
    - energy: column `value` (PJ). Not modified.

    Returns a copy with `value` rounded.

    Examples
    --------
    >>> round_energy_use(pd.DataFrame({"value": [1.23456, 0.0049]}))["value"].tolist()
    [1.23, 0.0]
    """
    return energy.assign(value=energy["value"].round(2))


def energy_use_by_period(
    energy: pd.DataFrame, projection_years: dict[int, int]
) -> pd.DataFrame:
    """
    Energy demand of each model period: the CEF value of the year the period reads
    (see `canoe.common.periods.projection_year_by_period`).

    params:
    - energy: columns `region`, `year`, `fuel`, `value` (PJ). Not modified.
    - projection_years: model period -> year

    Returns region, period, fuel, value (PJ).

    Raises
    ------
    ValueError
        If CEF has no data for a year read.

    Examples
    --------
    >>> energy = pd.DataFrame(
    ...     {"region": "ON", "year": [2030, 2035], "fuel": "NG", "value": [1.0, 2.0]}
    ... )
    >>> energy_use_by_period(energy, {2025: 2030, 2030: 2035})[["period", "value"]]
       period  value
    0    2025    1.0
    1    2030    2.0
    """
    missing = sorted(set(projection_years.values()) - set(energy["year"]))
    if missing:
        raise ValueError(
            f"CEF end-use demand has no data for the years {missing}; it covers "
            + f"{energy['year'].min()}-{energy['year'].max()}"
        )
    period_of_year = pd.DataFrame(
        {"period": list(projection_years), "year": list(projection_years.values())}
    )
    return energy.merge(period_of_year, on="year")[
        ["region", "period", "fuel", "value"]
    ]  # pyright: ignore[reportReturnType]


def compute_demand_and_splits(
    energy: pd.DataFrame, small_share_threshold: float, strategy: SmallShareStrategy
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Sector demand and share of each fuel, by province and period.

    params:
    - energy: energy demand, columns `region`, `period`, `fuel`, `value` (PJ). Not
      modified.
    - small_share_threshold: shares below it become zero (see `SmallShareStrategy`)

    Returns
    - demand: region, period, demand (PJ), rounded to 0.01 PJ like the energy
    - splits: region, period, fuel, split (0-1), for every fuel the technology takes
      in the province, in every period (zero where the fuel's share is small); the
      splits of a province and period add up to 1

    Raises
    ------
    ValueError
        If every share of a province and period is small.

    Examples
    --------
    >>> energy = pd.DataFrame(
    ...     {
    ...         "region": "ON",
    ...         "period": [2025, 2025, 2025, 2030, 2030, 2030],
    ...         "fuel": ["GSL", "ELC", "NG", "GSL", "ELC", "NG"],
    ...         "value": [97.0, 2.0, 1.0, 90.0, 9.0, 1.0],
    ...     }
    ... )
    >>> demand, splits = compute_demand_and_splits(
    ...     energy, 0.05, SmallShareStrategy.ZeroSmallShares
    ... )
    >>> demand
      region  period  demand
    0     ON    2025   100.0
    1     ON    2030   100.0
    >>> splits.round(3)
      region  period fuel  split
    0     ON    2025  ELC  0.000
    1     ON    2025  GSL  1.000
    2     ON    2030  ELC  0.091
    3     ON    2030  GSL  0.909
    >>> demand, _ = compute_demand_and_splits(
    ...     energy, 0.05, SmallShareStrategy.DropSmallFuels
    ... )
    >>> demand["demand"].tolist()
    [99.0, 99.0]
    """
    keys = ["region", "period"]
    shares = energy.assign(
        share=energy["value"] / energy.groupby(keys)["value"].transform("sum")
    )

    # Fuels taken in a province: used, and not below the threshold in some period
    large = (shares["share"] >= small_share_threshold) & (shares["share"] > 0)
    taken = large.groupby([shares["region"], shares["fuel"]]).transform("any")
    taken_shares: pd.DataFrame = shares.loc[taken.astype(bool)]

    if strategy == SmallShareStrategy.DropSmallFuels:
        # Fuels not taken leave the demand, and the shares are of what is left
        demand_energy = taken_shares
        remaining = taken_shares["value"] / taken_shares.groupby(keys)[
            "value"
        ].transform("sum")
        kept_share = remaining.where(remaining > small_share_threshold, 0.0)
    else:
        demand_energy = shares
        share = taken_shares["share"]
        kept_share = share.where(share >= small_share_threshold, 0.0)

    total = (
        demand_energy["value"]
        .groupby([demand_energy["region"], demand_energy["period"]])
        .transform("sum")
    )
    demand = (
        pd.DataFrame(
            {
                "region": demand_energy["region"],
                "period": demand_energy["period"],
                "demand": total.round(2),
            }
        )
        .drop_duplicates(subset=keys)
        .reset_index(drop=True)
    )

    share_total = kept_share.groupby(
        [taken_shares["region"], taken_shares["period"]]
    ).transform("sum")
    no_share: pd.DataFrame = taken_shares.loc[share_total == 0, keys]
    if not no_share.empty:
        raise ValueError(
            "every fuel share is below small_share_threshold = "
            + f"{small_share_threshold} in: "
            + ", ".join(
                f"{r} {p}"
                for r, p in no_share.drop_duplicates().itertuples(index=False)
            )
        )
    splits = pd.DataFrame(
        {
            "region": taken_shares["region"],
            "period": taken_shares["period"],
            "fuel": taken_shares["fuel"],
            "split": kept_share / share_total,
        }
    )
    return demand, splits.sort_values(by=["region", "period", "fuel"]).reset_index(
        drop=True
    )

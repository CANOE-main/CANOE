"""
Input splits of the agriculture technology: the fuel mix of agriculture energy use.

The CEUD fuel mix of each province, from `energy_use.compute_energy_use_by_source`,
becomes the share of each requested fuel with the selected `InputSplitStrategy`. The
fuel mix is that of the data year, kept constant over the model periods. Nothing in
here touches the database.
"""

from enum import StrEnum

import numpy as np
import pandas as pd

from canoe.common import CANOEFuel


class InputSplitStrategy(StrEnum):
    """
    How the NRCan CEUD fuel mix of agriculture energy use becomes the input splits of
    the agriculture technology.

    The CEUD tables also report fuels that are not modelled (e.g. light fuel oil,
    kerosene or steam, or any supported fuel left out of `fuels`); strategies differ
    in what happens to their share.
    """

    NRCanPercentWithRemainder = "nrcan_percent_with_remainder"
    """Shares as published by NRCan (percent, one decimal), rounded to 3 decimals.
    The share of the fuels not modelled goes to `remainder_fuel`, so the splits add
    up to 0.999. Reproduces the previous agriculture module."""

    EnergyWithRemainder = "energy_with_remainder"
    """Energy use of each fuel (PJ) divided by the total energy use. The share of the
    fuels not modelled goes to `remainder_fuel`, so the splits add up to 1."""

    EnergyNormalized = "energy_normalized"
    """Energy use of each modelled fuel (PJ) divided by the energy use of all modelled
    fuels. The share of the fuels not modelled is spread over the modelled ones in
    proportion to their energy use; the splits add up to 1."""

    def uses_remainder_fuel(self) -> bool:
        """
        Whether the share of the fuels not modelled goes to `remainder_fuel`.

        Examples
        --------
        >>> InputSplitStrategy.EnergyWithRemainder.uses_remainder_fuel()
        True
        >>> InputSplitStrategy.EnergyNormalized.uses_remainder_fuel()
        False
        """
        return self != InputSplitStrategy.EnergyNormalized


def compute_input_splits(
    energy_use_by_source: pd.DataFrame,
    fuels: list[CANOEFuel],
    strategy: InputSplitStrategy,
    remainder_fuel: CANOEFuel,
    model_periods: list[int],
) -> pd.DataFrame:
    """
    Share of each requested fuel in the agriculture energy use of each province.

    params:
    - energy_use_by_source: see `energy_use.compute_energy_use_by_source`. Not modified.
    - fuels: fuels requested in the config, in order (the order breaks ties in
      `nrcan_percent_with_remainder_splits`)
    - remainder_fuel: fuel taking the share of the sources not modelled; ignored by
      strategies that don't use it

    Returns region, period, fuel, split (0-1): one row per fuel with a split, the
    same in every model period. Fuels a province does not use have no row.

    Raises
    ------
    ValueError
        If a province uses none of the requested fuels.
    """
    rows: list[tuple[object, CANOEFuel, float]] = []
    for province, df in energy_use_by_source.groupby("province", sort=False):
        # Each requested fuel has a single CEUD source
        by_fuel = {fuel: df.loc[df["fuel"].isin([fuel])].iloc[0] for fuel in fuels}
        if strategy == InputSplitStrategy.NRCanPercentWithRemainder:
            splits = nrcan_percent_with_remainder_splits(
                {fuel: float(row["share"]) for fuel, row in by_fuel.items()},
                remainder_fuel,
            )
        elif strategy == InputSplitStrategy.EnergyWithRemainder:
            splits = energy_with_remainder_splits(
                {fuel: float(row["energy_use"]) for fuel, row in by_fuel.items()},
                float(np.nansum(df["energy_use"].to_numpy(dtype=float))),
                remainder_fuel,
            )
        else:
            splits = energy_normalized_splits(
                {fuel: float(row["energy_use"]) for fuel, row in by_fuel.items()}
            )
        if not splits:
            raise ValueError(
                f"{province} uses none of the requested agriculture fuels "
                + f"{[f.value for f in fuels]}"
            )
        rows += [(province, fuel, split) for fuel, split in splits.items()]

    return pd.DataFrame(rows, columns=["region", "fuel", "split"]).merge(
        pd.DataFrame({"period": model_periods}), how="cross"
    )[["region", "period", "fuel", "split"]]  # pyright: ignore[reportReturnType]


def nrcan_percent_with_remainder_splits(
    shares: dict[CANOEFuel, float], remainder_fuel: CANOEFuel
) -> dict[CANOEFuel, float]:
    """
    Splits from the shares NRCan publishes, as the previous agriculture module did.

    - Shares are rounded to 3 decimals; fuels with a zero share are left out and
      shares NRCan does not publish (NaN) are "not available".
    - If the known shares add up to more than 1, the excess is taken from the
      smallest one (the first, in `shares` order).
    - If they add up to less than 1, the gap up to **0.999** goes to
      `remainder_fuel` (added to its share, replacing it if not available, or as a
      new split if it has none).
    - Shares still not available split what is left up to 1 equally.

    params:
    - shares: share (0-1) of each requested fuel, in config order

    Returns fuel -> split, in `shares` order (the remainder fuel last if added).

    Examples
    --------
    Ontario, 2022: the 6.5% of light fuel oil, kerosene and propane goes to diesel.

    >>> nrcan_percent_with_remainder_splits(
    ...     {
    ...         CANOEFuel.Electricity: 0.149,
    ...         CANOEFuel.NaturalGas: 0.42,
    ...         CANOEFuel.Diesel: 0.252,
    ...         CANOEFuel.Gasoline: 0.113,
    ...     },
    ...     CANOEFuel.Diesel,
    ... )
    {Electricity: 0.149, NaturalGas: 0.42, Diesel: 0.317, Gasoline: 0.113}

    A fuel not published takes what the others leave:

    >>> nrcan_percent_with_remainder_splits(
    ...     {CANOEFuel.Electricity: 0.3, CANOEFuel.NaturalGas: float("nan")},
    ...     CANOEFuel.Diesel,
    ... )
    {Electricity: 0.3, NaturalGas: 0.001, Diesel: 0.699}
    """
    # None: share not available
    values: dict[CANOEFuel, float | None] = {}
    for fuel, share in shares.items():
        if np.isnan(share):
            values[fuel] = None
        elif share != 0:
            values[fuel] = round(share, 3)
    not_available = sum(v is None for v in values.values())

    def known_total() -> float:
        return sum(v for v in values.values() if v is not None)

    total = known_total()
    # More than 1: correct the smallest value downward
    if total > 1.0:
        excess = round(total - 1.0, 3)
        smallest = min(v for v in values.values() if v is not None)
        fuel = next(f for f, v in values.items() if v == smallest)
        values[fuel] = max(0.0, round(smallest - excess, 3))
        total = known_total()

    # Less than 1: the remainder (up to 0.999) goes to the remainder fuel
    if total < 1.0:
        remainder = round(0.999 - total, 3)
        current = values.get(remainder_fuel)
        values[remainder_fuel] = (
            remainder if current is None else round(current + remainder, 3)
        )
        total = known_total()

    return {
        fuel: value
        if value is not None
        else round(max(0.0, 1.0 - total) / not_available, 3)
        for fuel, value in values.items()
    }


def energy_with_remainder_splits(
    energy_use: dict[CANOEFuel, float],
    total_energy_use: float,
    remainder_fuel: CANOEFuel,
) -> dict[CANOEFuel, float]:
    """
    Energy use of each fuel over the total; the rest goes to `remainder_fuel`.

    Fuels with no (or unknown, NaN) energy use are left out. The splits add up to 1.

    params:
    - energy_use: energy use (PJ) of each requested fuel, in config order
    - total_energy_use: energy use (PJ) of all sources NRCan publishes, modelled or not

    Examples
    --------
    >>> energy_with_remainder_splits(
    ...     {CANOEFuel.Electricity: 2.0, CANOEFuel.Diesel: 5.0, CANOEFuel.NaturalGas: 0.0},
    ...     8.0,
    ...     CANOEFuel.Diesel,
    ... )
    {Electricity: 0.25, Diesel: 0.75}
    """
    splits = {
        fuel: energy / total_energy_use
        for fuel, energy in energy_use.items()
        if not np.isnan(energy) and energy > 0
    }
    remainder = 1.0 - sum(splits.values())
    if remainder > 0:
        splits[remainder_fuel] = splits.get(remainder_fuel, 0.0) + remainder
    return splits


def energy_normalized_splits(
    energy_use: dict[CANOEFuel, float],
) -> dict[CANOEFuel, float]:
    """
    Energy use of each fuel over the energy use of all requested fuels.

    Fuels with no (or unknown, NaN) energy use are left out. The splits add up to 1.

    params:
    - energy_use: energy use (PJ) of each requested fuel, in config order

    Examples
    --------
    >>> energy_normalized_splits(
    ...     {CANOEFuel.Electricity: 2.0, CANOEFuel.Diesel: 6.0, CANOEFuel.NaturalGas: 0.0}
    ... )
    {Electricity: 0.25, Diesel: 0.75}
    """
    used = {
        fuel: energy
        for fuel, energy in energy_use.items()
        if not np.isnan(energy) and energy > 0
    }
    total = sum(used.values())
    return {fuel: energy / total for fuel, energy in used.items()}

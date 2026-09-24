"""
Input splits of the agriculture technology: the fuel mix of agriculture energy use.
"""

from enum import StrEnum


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

"""
Emissions shared by all modules.

Modules write emission activities for the real gases (`CANOEEmission`). The central
emissions step registers the gas commodities before the modules run, and afterwards
adds a CO2-equivalent row for every emitting flow, weighting the gases by the global
warming potentials of the configured `GlobalWarmingPotential` set.
"""

from enum import StrEnum


class CANOEEmission(StrEnum):
    CO2 = "CO2"
    CH4 = "CH4"
    N2O = "N2O"

    def get_desc_name(self) -> str:
        _NAMES = {
            "CO2": "carbon dioxide",
            "CH4": "methane",
            "N2O": "nitrous oxide",
        }
        return _NAMES[self.value]


class GlobalWarmingPotential(StrEnum):
    """Sets of 100-year global warming potentials used to compute CO2-equivalents"""

    AR5_100 = "AR5-100"
    """IPCC Fifth Assessment Report (used by the previous version of the commercial
    module)."""

    def factors(self) -> dict[CANOEEmission, float]:
        """
        Examples
        --------
        >>> GlobalWarmingPotential.AR5_100.factors()[CANOEEmission.CH4]
        28.0
        """
        _FACTORS = {
            GlobalWarmingPotential.AR5_100: {
                CANOEEmission.CO2: 1.0,
                CANOEEmission.CH4: 28.0,
                CANOEEmission.N2O: 265.0,
            },
        }
        return _FACTORS[self]

    def get_desc_name(self) -> str:
        _NAMES = {
            GlobalWarmingPotential.AR5_100: "IPCC AR5, 100-year",
        }
        return _NAMES[self]

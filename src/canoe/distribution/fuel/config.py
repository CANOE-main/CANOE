from enum import StrEnum

from pydantic import BaseModel

from canoe.common import CANOEFuel


class FuelNamingConvention(StrEnum):
    Simple = "simple"

    def get_fuel_name(self, fuel: CANOEFuel) -> str:
        if self == FuelNamingConvention.Simple:
            return f"C_{fuel}"
        return str(fuel)  # Unreachable


class CANOEFuelDistributionConfig(BaseModel):
    naming_convention: FuelNamingConvention = FuelNamingConvention.Simple

from enum import StrEnum
from typing import Any, override


class CANOEFuel(StrEnum):
    """Fuels of the model. Configs take the value (e.g. `"ELC"`) or the name."""

    Electricity = "ELC"  # Not sure this belongs here but it's a good start
    Coal = "COAL"
    Oil = "OIL"
    Diesel = "DSL"
    Gasoline = "GSL"
    NaturalGas = "NG"
    CompressedNaturalGas = "CNG"
    Hydrogen = "H2"
    Ethanol = "ETH"
    Wood = "WOOD"
    NaturalGasLiquids = "NGL"
    LiquifiedNaturalGas = "LNG"
    LiquifiedPretroleumGas = "LPG"
    PetroleumCoke = "PCK"
    Coke = "COKE"
    Propane = "PROP"
    HeavyFuelOil = "HFO"
    RenewableDiesel = "RDSL"
    NaturalUranium = "NUR"
    EnrichedUranium = "EUR"
    JetFuel = "JTF"
    SyntheticJetFuel = "SPK"
    BioEnergy = "BIO"
    GaseousBioenergy = "GBIO"
    SolidBioenergy = "SBIO"
    MarineDieselOil = "MDO"
    Other = "OTH"

    @classmethod
    @override
    def _missing_(cls, value: Any):
        if isinstance(value, str) and value in cls.__members__:
            return cls.__members__[value]
        return None

    def get_desc_name(self) -> str:
        CANOE_FUEL_TO_NAME = {
            CANOEFuel.Electricity: "electricity",
            CANOEFuel.Coal: "coal",
            CANOEFuel.Oil: "oil",
            CANOEFuel.Diesel: "diesel",
            CANOEFuel.Gasoline: "gasoline",
            CANOEFuel.NaturalGas: "natural gas",
            CANOEFuel.CompressedNaturalGas: "compressed natural gas",
            CANOEFuel.Hydrogen: "hydrogen",
            CANOEFuel.Ethanol: "ethanol",
            CANOEFuel.Wood: "wood",
            CANOEFuel.NaturalGasLiquids: "natural gas liquids",
            CANOEFuel.LiquifiedNaturalGas: "liquefied natural gas",
            CANOEFuel.LiquifiedPretroleumGas: "liquefied petroleum gas (LPG) (primarily propane)",
            CANOEFuel.PetroleumCoke: "petroleum coke",
            CANOEFuel.Coke: "coke",
            CANOEFuel.Propane: "propane",
            CANOEFuel.HeavyFuelOil: "heavy fuel oil",
            CANOEFuel.RenewableDiesel: "renewable diesel",
            CANOEFuel.NaturalUranium: "natural uranium",
            CANOEFuel.EnrichedUranium: "enriched uranium",
            CANOEFuel.JetFuel: "jet fuel",
            CANOEFuel.SyntheticJetFuel: "synthetic jet fuel",
            CANOEFuel.BioEnergy: "bioenergy",
            CANOEFuel.GaseousBioenergy: "gaseous bioenergy",
            CANOEFuel.SolidBioenergy: "solid bioenergy",
            CANOEFuel.MarineDieselOil: "marine diesel oil",
            CANOEFuel.Other: "other fuels",
        }
        return CANOE_FUEL_TO_NAME[self]

    def get_price_fuel(self) -> "CANOEFuel":
        """
        Maps a fuel to the fuel whose price series it actually uses.
        """
        CANOE_FUEL_PRICE_OVERRIDES: dict[CANOEFuel, CANOEFuel] = {
            CANOEFuel.CompressedNaturalGas: CANOEFuel.NaturalGas,
            CANOEFuel.LiquifiedNaturalGas: CANOEFuel.NaturalGas,
            CANOEFuel.Wood: CANOEFuel.BioEnergy,
            CANOEFuel.NaturalGasLiquids: CANOEFuel.Propane,
            CANOEFuel.LiquifiedPretroleumGas: CANOEFuel.Propane,
            CANOEFuel.PetroleumCoke: CANOEFuel.Coal,
            CANOEFuel.Coke: CANOEFuel.Coal,
            CANOEFuel.GaseousBioenergy: CANOEFuel.BioEnergy,
            CANOEFuel.SolidBioenergy: CANOEFuel.BioEnergy,
            CANOEFuel.MarineDieselOil: CANOEFuel.Diesel,
        }
        return CANOE_FUEL_PRICE_OVERRIDES.get(self, self)

    @classmethod
    def from_str(cls, name: str) -> "CANOEFuel":
        # Try direct value match first (e.g. "ELC", "DSL")
        try:
            return cls(name)
        except ValueError:
            pass

        # Normalize to a lowercase, space-free string for name matching
        normalized = name.lower().replace(" ", "").replace("_", "")
        for fuel in cls:
            if fuel.name.lower() == normalized:
                return fuel

        raise ValueError(f"Unknown fuel: {name!r}")

    @override
    def __str__(self):
        return str(self.name)

    @override
    def __repr__(self):
        return str(self.name)

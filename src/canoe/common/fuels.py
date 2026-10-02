from enum import StrEnum
from typing import Any, override

from .sectors import CANOESector


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

    def get_eia_fuel(self, sector: CANOESector) -> str | None:
        """
        Fuel of the EIA AEO Table 3 'Energy Prices' series of this fuel in `sector`,
        if EIA has one. Whether EIA has the series for that sector is up to the data.

        Coal is the metallurgical coal series and oil the residual fuel series.

        Examples
        --------
        >>> CANOEFuel.Diesel.get_eia_fuel(CANOESector.Transportation)
        'Diesel Fuel'
        >>> CANOEFuel.Diesel.get_eia_fuel(CANOESector.Industry)
        'Distillate Fuel Oil'
        >>> CANOEFuel.Ethanol.get_eia_fuel(CANOESector.Transportation) is None
        True
        """
        # EIA names two fuels differently depending on the sector
        if self == CANOEFuel.Diesel:
            if sector == CANOESector.Transportation:
                return "Diesel Fuel"
            return "Distillate Fuel Oil"
        if self == CANOEFuel.Oil:
            if sector == CANOESector.Commercial:
                return "Residual Fuel"
            return "Residual Fuel Oil"
        EIA_FUELS: dict[CANOEFuel, str] = {
            CANOEFuel.Coal: "Metallurgical Coal",
            CANOEFuel.Gasoline: "Motor Gasoline",
            CANOEFuel.NaturalGas: "Natural Gas",
            CANOEFuel.Hydrogen: "Hydrogen",
            CANOEFuel.Propane: "Propane",
            CANOEFuel.HeavyFuelOil: "Residual Fuel Oil",
            CANOEFuel.JetFuel: "Jet Fuel",
        }
        return EIA_FUELS.get(self)

    def get_atb_technology(self) -> str | None:
        """
        NREL ATB technology whose fuel cost is the price of this fuel, if any.

        Examples
        --------
        >>> CANOEFuel.Wood.get_atb_technology()
        'Biopower'
        >>> CANOEFuel.NaturalGas.get_atb_technology() is None
        True
        """
        ATB_TECHNOLOGIES: dict[CANOEFuel, str] = {
            CANOEFuel.BioEnergy: "Biopower",
            CANOEFuel.GaseousBioenergy: "Biopower",
            CANOEFuel.SolidBioenergy: "Biopower",
            CANOEFuel.Wood: "Biopower",
            CANOEFuel.NaturalUranium: "Nuclear",
            CANOEFuel.EnrichedUranium: "Nuclear",
        }
        return ATB_TECHNOLOGIES.get(self)

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

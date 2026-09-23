from abc import ABC, abstractmethod
from dataclasses import dataclass

from .emissions import CANOEEmission
from .fuels import CANOEFuel
from .sectors import CANOESector


@dataclass
class CANOEFuelImport:
    sector: CANOESector
    fuel: CANOEFuel


@dataclass(frozen=True)
class CANOEEmissionDeclaration:
    """
    A gas a sector accounts for: it wrote emission activities for it. The central
    emissions step checks declarations against the rows in the database.
    """

    sector: CANOESector
    emission: CANOEEmission


class CANOEModuleOutput:
    """
    This is the interface for a module to communicate to the CANOE engine
    context what it needs hadled with global effects.
    """

    fuel_imports: list[CANOEFuelImport]
    emissions: list[CANOEEmissionDeclaration]

    def __init__(
        self,
        fuel_imports: list[CANOEFuelImport],
        emissions: list[CANOEEmissionDeclaration] | None = None,
    ) -> None:
        self.fuel_imports = fuel_imports
        self.emissions = emissions or []


class CANOEModule(ABC):
    @abstractmethod
    def run(self) -> CANOEModuleOutput:
        pass

    @abstractmethod
    def get_dataset_code(self) -> str:
        pass

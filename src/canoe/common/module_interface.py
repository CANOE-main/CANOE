from abc import ABC, abstractmethod
from dataclasses import dataclass

from .fuels import CANOEFuel
from .sectors import CANOESector


@dataclass
class CANOEFuelImport:
    sector: CANOESector
    fuel: CANOEFuel


class CANOEModuleOutput:
    """
    This is the interface for a module to communicate to the CANOE engine
    context what it needs hadled with global effects.
    """

    fuel_imports: list[CANOEFuelImport]

    def __init__(self, fuel_imports: list[CANOEFuelImport]) -> None:
        self.fuel_imports = fuel_imports


class CANOEModule(ABC):
    @abstractmethod
    def run(self) -> CANOEModuleOutput:
        pass

    @abstractmethod
    def get_dataset_code(self) -> str:
        pass

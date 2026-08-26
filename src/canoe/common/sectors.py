from enum import StrEnum
from typing import Any, override


class CANOESector(StrEnum):
    Commercial = "COM"
    Residential = "RES"
    Industry = "IND"
    Transportation = "TRP"
    Agriculture = "AGR"

    @classmethod
    @override
    def _missing_(cls, value: Any):
        if isinstance(value, str) and value in cls.__members__:
            return cls.__members__[value]
        for member in cls:
            if value == member.get_tag():
                return member
        return None

    def get_tag(self):
        _TAGS = {
            "COM": "C",
            "RES": "R",
            "IND": "I",
            "TRP": "T",
            "AGR": "A",
        }
        return _TAGS[self.value]

    @override
    def __str__(self):
        return str(self.name)

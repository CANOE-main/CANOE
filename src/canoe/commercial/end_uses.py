"""
Commercial end uses.

Lives in its own module (instead of `config.py`) so that data and build modules can use
it at runtime without importing the configuration, which imports `build.py`.
"""

from enum import StrEnum
from typing import Any, override


class CommercialEndUse(StrEnum):
    SpaceHeating = "heating"
    SpaceCooling = "cooling"
    Other = "other"

    @classmethod
    @override
    def _missing_(cls, value: Any):
        if isinstance(value, str) and value in cls.__members__:
            return cls.__members__[value]
        for member in cls:
            if value == member.get_full_name():
                return member
        return None

    def get_full_name(self):
        _NAMES = {
            "heating": "space heating",
            "cooling": "space cooling",
            "other": "other",
        }
        return _NAMES[self.value]

    def get_short_name(self):
        _NAMES = {
            "heating": "sph",
            "cooling": "spc",
            "other": "oth",
        }
        return _NAMES[self.value]

    @override
    def __str__(self):
        return str(self.name)

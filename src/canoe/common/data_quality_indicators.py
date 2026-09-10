from typing import Any

from canoe_schema.v4_0 import (
    DataQualityCredibilityLevel,
    DataQualityGeographyLevel,
    DataQualityStructure,
    DataQualityTechnology,
    DataQualityTime,
)
from pydantic import BaseModel


class DataQualityProfile(BaseModel):
    cred: DataQualityCredibilityLevel | int
    geog: DataQualityGeographyLevel | int
    struc: DataQualityStructure | int
    tech: DataQualityTechnology | int
    time: DataQualityTime | int

    def as_kwargs(self) -> Any:
        return {f"dq_{k}": v for k, v in self.model_dump().items()}

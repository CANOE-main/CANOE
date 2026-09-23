"""
Containers for parameter values and the metadata that goes with them.

Entities store their parameters as `Parameter` (a labeled array plus notes, data
source, data quality and units) and a single `RowOptions` describing how that
metadata is spread over the rows. Schema rows are still built explicitly in each
entity's `build()`.
"""

from dataclasses import dataclass, field
from typing import Any

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.common import CANOEProvince, DataQualityProfile
from canoe.common.naming import DatasetIdentifier


@dataclass(frozen=True)
class ParameterMetadata:
    notes: str | None = None
    reference_code: str | None = None
    data_quality: DataQualityProfile | None = None
    units: str | None = None


@dataclass(frozen=True)
class Parameter[A: LabeledArray]:
    values: A
    metadata: ParameterMetadata = field(default_factory=ParameterMetadata)


@dataclass(frozen=True)
class RowOptions:
    """How metadata is spread over the rows written for a parameter"""

    data_id: DatasetIdentifier
    include_region_in_data_id: bool = True
    notes_only_on_first: bool = True
    reference_only_on_first: bool = True

    def notes(self, metadata: ParameterMetadata, row_index: int) -> str | None:
        if row_index == 0 or not self.notes_only_on_first:
            return metadata.notes
        return None

    def reference(self, metadata: ParameterMetadata, row_index: int) -> str | None:
        if row_index == 0 or not self.reference_only_on_first:
            return metadata.reference_code
        return None

    def data_quality(
        self, metadata: ParameterMetadata, row_index: int
    ) -> dict[str, Any]:
        """dq_* kwargs, on the first row only"""
        if row_index == 0 and metadata.data_quality:
            return metadata.data_quality.as_kwargs()
        return {}

    def dataset_code(self, region: CANOEProvince | None = None) -> str:
        return self.data_id.get_dataset_code(
            province=region if self.include_region_in_data_id else None
        )

"""
Containers for parameter values and the metadata that goes with them.

Entities (`TechnologyEntity`, `DemandEntity`, ...) store each parameter as a
`Parameter`: a labeled array of values plus a `ParameterMetadata` with the notes,
data source, data quality and units written alongside those values. A single
`RowOptions` per entity decides how that metadata is spread over the rows. The
schema rows themselves are built explicitly in each entity's `build()`, so the
mapping from values to database columns stays visible there.
"""

from dataclasses import dataclass, field
from typing import Any

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.common import CANOEProvince, DataQualityProfile
from canoe.common.naming import DatasetIdentifier


@dataclass(frozen=True)
class ParameterMetadata:
    """
    Metadata written alongside the values of a parameter.

    Parameters
    ----------
    notes : str, optional
        Free-text notes (`notes` column), usually how the values were estimated.
    reference_code : str, optional
        Id of the data source (`data_source` column).
    data_quality : DataQualityProfile, optional
        Data quality indicators (`dq_*` columns).
    units : str, optional
        Units of the values (`units` column), for tables that have one.
    """

    notes: str | None = None
    reference_code: str | None = None
    data_quality: DataQualityProfile | None = None
    units: str | None = None


@dataclass(frozen=True)
class Parameter[A: LabeledArray]:
    """
    Values of a parameter and their metadata.

    Parameters
    ----------
    values : LabeledArray
        One value per coordinate combination. NaN cells are not written.
    metadata : ParameterMetadata
        Notes, data source, data quality and units for the values.

    Examples
    --------
    >>> from canoe.canoe_objects.array_types import RegionalValuesArray
    >>> lifetime = Parameter(
    ...     RegionalValuesArray([CANOEProvince.ONTARIO], fill=20),
    ...     ParameterMetadata(notes="Average life of installed stock", units="year"),
    ... )
    >>> lifetime.values.to_records()
    [{'region': <CANOEProvince.ONTARIO: 'Ontario'>, 'value': np.float64(20.0)}]
    >>> lifetime.metadata.units
    'year'
    """

    values: A
    metadata: ParameterMetadata = field(default_factory=ParameterMetadata)


@dataclass(frozen=True)
class RowOptions:
    """
    How the metadata of a parameter is spread over the rows written for it.

    Each method returns the value of one column for the row at `row_index` (the
    position of the row among the rows written for that parameter).

    Parameters
    ----------
    data_id : DatasetIdentifier
        Data set the rows belong to.
    include_region_in_data_id : bool
        Use the per-region data set (e.g. `COMHRON003`) for rows with a region,
        instead of the sector-wide one (e.g. `COMHR003`).
    notes_only_on_first : bool
        Write the notes on the first row only, instead of on every row.
    reference_only_on_first : bool
        Write the data source on the first row only, instead of on every row.

    Notes
    -----
    Data quality indicators are always written on the first row only.

    Examples
    --------
    >>> from canoe.common import CANOESector
    >>> options = RowOptions(DatasetIdentifier(CANOESector.Commercial, "DOC", "001"))
    >>> metadata = ParameterMetadata(
    ...     notes="Estimated from AEO",
    ...     data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
    ... )
    >>> options.notes(metadata, 0), options.notes(metadata, 1)
    ('Estimated from AEO', None)
    >>> options.data_quality(metadata, 0)
    {'dq_cred': 1, 'dq_geog': 2, 'dq_struc': 2, 'dq_tech': 2, 'dq_time': 3}
    >>> options.data_quality(metadata, 1)
    {}
    >>> options.dataset_code(CANOEProvince.ONTARIO), options.dataset_code()
    ('COMDOCON001', 'COMDOC001')
    """

    data_id: DatasetIdentifier
    include_region_in_data_id: bool = True
    notes_only_on_first: bool = True
    reference_only_on_first: bool = True

    def notes(self, metadata: ParameterMetadata, row_index: int) -> str | None:
        """Value of the `notes` column"""
        if row_index == 0 or not self.notes_only_on_first:
            return metadata.notes
        return None

    def reference(self, metadata: ParameterMetadata, row_index: int) -> str | None:
        """Value of the `data_source` column"""
        if row_index == 0 or not self.reference_only_on_first:
            return metadata.reference_code
        return None

    def data_quality(
        self, metadata: ParameterMetadata, row_index: int
    ) -> dict[str, Any]:
        """Keyword arguments for the `dq_*` columns (empty after the first row)"""
        if row_index == 0 and metadata.data_quality:
            return metadata.data_quality.as_kwargs()
        return {}

    def dataset_code(self, region: CANOEProvince | None = None) -> str:
        """Value of the `data_id` column for a row in `region` (None: no region)"""
        return self.data_id.get_dataset_code(
            province=region if self.include_region_in_data_id else None
        )

"""
End-use demands: the demand commodity, its projected values and its time profile.

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py` (data sets `COMDOC*`, regions ON/QC, periods 2020-2035,
season D001 and times of day H01/H02).
"""

from sqlite3 import Connection

import numpy as np
from canoe_schema.v4_0 import (
    Commodity,
    CommodityTypeCode,
    Demand,
    DemandSpecificDistribution,
)

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.canoe_objects.parameter import Parameter, ParameterMetadata, RowOptions
from canoe.common import CANOEProvince, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import DatasetIdentifier


class DemandSpecificDistributionArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        period: list[int],
        season: list[str],
        tod: list[str],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
            "period": period,
            "season": season,
            "tod": tod,
        }
        super().__init__(coords, fill)


class DemandSeriesArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        period: list[int],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
            "period": period,
        }
        super().__init__(coords, fill)


class DemandEntity:
    """
    A demand commodity with its projected demand and, optionally, its demand-specific
    distribution (DSD) over time slices.

    Configure it with `with_demand_series` (required) and `with_dsd`, then write it
    with `build`. Both are labeled arrays; `build` writes one row per non-NaN cell,
    converting regions to their short code and filling notes, data source, data
    quality and `data_id` as described by `RowOptions`.

    Parameters
    ----------
    name : str
        Name of the demand commodity.
    commodity_description : str
        Description in the `commodity` table.
    unit : str
        Units of the demand, written to `commodity` and `demand`.
    data_id : DatasetIdentifier
        Data set the rows belong to.
    notes_only_on_first, reference_only_on_first, include_region_in_data_id : bool
        How metadata is spread over rows, see `RowOptions`.

    Examples
    --------
    >>> from canoe.common import CANOESector
    >>> regions = [CANOEProvince.ONTARIO]
    >>> demand = DemandSeriesArray(regions, [2025, 2030])
    >>> demand.set(100.0, period=2025)
    >>> demand.set(110.0, period=2030)
    >>> dsd = DemandSpecificDistributionArray(regions, [2025, 2030], ["D001"], ["H01", "H02"])
    >>> dsd.set(0.3, tod="H01")
    >>> dsd.set(0.7, tod="H02")
    >>> entity = (
    ...     DemandEntity(
    ...         name="C_D_DOC",
    ...         commodity_description="demand for commercial documentation",
    ...         unit="PJ",
    ...         data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ...     )
    ...     .with_demand_series(demand, notes="Base-year demand indexed to GDP")
    ...     .with_dsd(dsd, notes="Normalized hourly profile")
    ... )
    >>> entity.build(db)
    >>> db.execute("SELECT name, flag, units FROM commodity").fetchall()
    [('C_D_DOC', 'd', 'PJ')]
    >>> for row in db.execute("SELECT region, period, commodity, demand, units, notes FROM demand"):
    ...     print(row)
    ('ON', 2025, 'C_D_DOC', 100.0, 'PJ', 'Base-year demand indexed to GDP')
    ('ON', 2030, 'C_D_DOC', 110.0, 'PJ', None)
    >>> for row in db.execute(
    ...     "SELECT region, period, season, tod, dsd FROM demand_specific_distribution"
    ... ):
    ...     print(row)
    ('ON', 2025, 'D001', 'H01', 0.3)
    ('ON', 2025, 'D001', 'H02', 0.7)
    ('ON', 2030, 'D001', 'H01', 0.3)
    ('ON', 2030, 'D001', 'H02', 0.7)
    """

    def __init__(
        self,
        name: str,
        commodity_description: str,
        unit: str,
        data_id: DatasetIdentifier,
        notes_only_on_first: bool = True,
        reference_only_on_first: bool = True,
        include_region_in_data_id: bool = True,
    ):
        self.name: str = name
        self.flag: CommodityTypeCode = CommodityTypeCode.D
        self.commodity_description: str = commodity_description
        self.unit: str = unit
        self.row_options: RowOptions = RowOptions(
            data_id=data_id,
            include_region_in_data_id=include_region_in_data_id,
            notes_only_on_first=notes_only_on_first,
            reference_only_on_first=reference_only_on_first,
        )

        self.dsd: Parameter[DemandSpecificDistributionArray] | None = None
        self.demand: Parameter[DemandSeriesArray] | None = None

    def with_dsd(
        self,
        dsd_array: DemandSpecificDistributionArray,
        notes: str | None,
        reference_code: str | None = None,
        data_quality: DataQualityProfile | None = None,
    ) -> "DemandEntity":
        """
        Set the demand-specific distribution: the fraction of each period's demand
        that falls in each time slice.

        Writes `demand_specific_distribution`: one row per (region, period, season,
        time of day) with a value. Values should add up to 1 over the time slices of
        each region and period.

        Parameters
        ----------
        dsd_array : DemandSpecificDistributionArray
            Fractions by region, period, season and time of day.
        notes : str or None
            Notes, see `ParameterMetadata`.
        reference_code, data_quality : optional
            Data source and data quality, see `ParameterMetadata`.
        """
        self.dsd = Parameter(
            dsd_array, ParameterMetadata(notes, reference_code, data_quality)
        )
        return self

    def with_demand_series(
        self,
        demand_array: DemandSeriesArray,
        notes: str | None = None,
        reference_code: str | None = None,
        data_quality: DataQualityProfile | None = None,
    ) -> "DemandEntity":
        """
        Set the projected demand.

        Writes `demand`: one row per (region, period) with a value, in the entity's
        `unit`.

        Parameters
        ----------
        demand_array : DemandSeriesArray
            Demand by region and period.
        notes, reference_code, data_quality : optional
            Notes, data source and data quality, see `ParameterMetadata`.
        """
        self.demand = Parameter(
            demand_array,
            ParameterMetadata(notes, reference_code, data_quality, units=self.unit),
        )
        return self

    def build(self, db_conn: Connection):
        """
        Write the demand commodity, its demand and (if set) its DSD to the database.

        Rows that already exist are left untouched (insert or ignore).

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.

        Raises
        ------
        ValueError
            If no demand series was set.
        """
        if self.demand is None:
            raise ValueError("demand must be set before building")
        options = self.row_options

        # Build commodities
        commodity = Commodity(
            name=self.name,
            flag=self.flag,
            description=self.commodity_description,
            units=self.unit,
            data_id=options.dataset_code(),
        )
        sql, params = Commodity.to_insert_or_ignore_sql(commodity)
        write_label(db_conn, commodity)
        db_conn.execute(sql, params)

        # Build Demand series
        meta = self.demand.metadata
        demands = [
            Demand(
                region=row["region"].short(),
                period=row["period"],
                commodity=self.name,
                demand=row["value"],
                units=meta.units,
                notes=options.notes(meta, i),
                data_source=options.reference(meta, i),
                data_id=options.dataset_code(row["region"]),
                **options.data_quality(meta, i),
            )
            for i, row in enumerate(self.demand.values.to_records())
        ]
        sql, params = Demand.bulk_insert_or_ignore_sql(demands, include_nulls=True)
        db_conn.executemany(sql, params)

        # Build DSD
        if self.dsd is not None:
            meta = self.dsd.metadata
            dsds = [
                DemandSpecificDistribution(
                    region=row["region"].short(),
                    period=row["period"],
                    season=row["season"],
                    tod=row["tod"],
                    demand_name=self.name,
                    dsd=row["value"],
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.dsd.values.to_records())
            ]
            sql, params = DemandSpecificDistribution.bulk_insert_or_ignore_sql(
                dsds, include_nulls=True
            )
            db_conn.executemany(sql, params)

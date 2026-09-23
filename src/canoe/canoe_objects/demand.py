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
        self.demand = Parameter(
            demand_array,
            ParameterMetadata(notes, reference_code, data_quality, units=self.unit),
        )
        return self

    def build(self, db_conn: Connection):
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

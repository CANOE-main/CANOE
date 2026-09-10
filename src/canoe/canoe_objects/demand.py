from sqlite3 import Connection

import numpy as np
from canoe_schema.v4_0 import (
    Commodity,
    CommodityTypeCode,
    Demand,
    DemandSpecificDistribution,
)

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.common import CANOEProvince, DataQualityProfile
from canoe.common.db_tools import write_label


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
        data_id: str,
        notes_only_on_first: bool = True,
        reference_only_on_first: bool = True,
    ):
        self.name: str = name
        self.flag: CommodityTypeCode = CommodityTypeCode.D
        self.commodity_description: str = commodity_description
        self.unit: str = unit
        self.data_id: str = data_id
        self.notes_only_on_first: bool = notes_only_on_first
        self.reference_only_on_first: bool = reference_only_on_first

        self.dsd: DemandSpecificDistributionArray | None = None
        self.dsd_notes: str | None = None
        self.dsd_reference_code: str | None
        self.dsd_data_quality: DataQualityProfile | None = None

        self.demand: DemandSeriesArray | None = None
        self.demand_notes: str | None = None
        self.demand_reference_code: str | None
        self.demand_data_quality: DataQualityProfile | None = None

    def with_dsd(
        self,
        dsd_array: DemandSpecificDistributionArray,
        notes: str | None,
        reference_code: str | None = None,
        data_quality: DataQualityProfile | None = None,
    ) -> "DemandEntity":
        self.dsd = dsd_array

        # DSD secondary parameters
        self.dsd_notes = notes
        self.dsd_reference_code = reference_code
        self.dsd_data_quality = data_quality
        return self

    def with_demand_series(
        self,
        demand_array: DemandSeriesArray,
        notes: str | None = None,
        reference_code: str | None = None,
        data_quality: DataQualityProfile | None = None,
    ) -> "DemandEntity":
        self.demand = demand_array

        # Demand secondary parameters
        self.demand_notes = notes
        self.demand_reference_code = reference_code
        self.demand_data_quality = data_quality
        return self

    def build(self, db_conn: Connection):
        if self.demand is None:
            raise ValueError("demand must be set before building")

        # Build commodities
        commodity = Commodity(
            name=self.name,
            flag=self.flag,
            description=self.commodity_description,
            units=self.unit,
            data_id=self.data_id,
        )
        sql, params = Commodity.to_insert_or_ignore_sql(commodity)
        write_label(db_conn, commodity)
        db_conn.execute(sql, params)

        # Build Demand series
        demands = [
            Demand(
                region=row["region"],
                period=row["period"],
                commodity=self.name,
                demand=row["value"],
                units=self.unit,
                notes=self.demand_notes
                if i == 0 or not self.notes_only_on_first
                else None,
                data_source=self.demand_reference_code
                if i == 0 or not self.reference_only_on_first
                else None,
                data_id=self.data_id,
                **(
                    self.demand_data_quality.as_kwargs()
                    if self.demand_data_quality and i == 0
                    else {}
                ),
            )
            for i, row in enumerate(self.demand.to_records())
        ]
        sql, params = Demand.bulk_insert_or_ignore_sql(demands, include_nulls=True)
        db_conn.executemany(sql, params)

        # Build DSD
        if self.dsd is not None:
            dsds = [
                DemandSpecificDistribution(
                    region=row["region"],
                    period=row["period"],
                    season=row["season"],
                    tod=row["tod"],
                    demand_name=self.name,
                    dsd=row["value"],
                    notes=self.dsd_notes
                    if i == 0 or not self.notes_only_on_first
                    else None,
                    data_source=self.dsd_reference_code
                    if i == 0 or not self.reference_only_on_first
                    else None,
                    data_id=self.data_id,
                    **(
                        self.dsd_data_quality.as_kwargs()
                        if self.dsd_data_quality and i == 0
                        else {}
                    ),
                )
                for i, row in enumerate(self.dsd.to_records())
            ]
            sql, params = DemandSpecificDistribution.bulk_insert_or_ignore_sql(
                dsds, include_nulls=True
            )
            db_conn.executemany(sql, params)

from sqlite3 import Connection
from typing import Any

import numpy as np
import pandas as pd
from canoe_schema.v4_0 import (
    CapacityToActivity,
    LifetimeTech,
    Technology,
    TechnologyTypeCode,
)

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import DatasetIdentifier, TechnologyCapacityScope


class RegionalValuesArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
        }
        super().__init__(coords, fill)


class FuelServingTechnologyEntity:
    """
    Builds technologies that serve an end-use demand using various input fuels.
    """

    def __init__(
        self,
        sector: CANOESector,
        demand_short_name: str,
        fuels: list[CANOEFuel],
        data_id: DatasetIdentifier,
        capacity_scope: TechnologyCapacityScope | None = None,
        tech_flag: TechnologyTypeCode = TechnologyTypeCode.P,
        include_region_in_data_id: bool = True,
        notes_only_on_first: bool = True,
        reference_only_on_first: bool = True,
    ) -> None:
        self.tech_flag: TechnologyTypeCode = tech_flag
        self.demand_short_name: str = demand_short_name
        self.sector: CANOESector = sector
        self.fuels: list[CANOEFuel] = fuels
        self.data_id: DatasetIdentifier = data_id
        self.include_region_in_data_id: bool = include_region_in_data_id
        self.capacity_scope_str: str = (
            f"-{capacity_scope.value}" if capacity_scope else ""
        )
        self.notes_only_on_first: bool = notes_only_on_first
        self.reference_only_on_first: bool = reference_only_on_first

        self.annual: int = 0

        self.lifetimes: dict[CANOEFuel, RegionalValuesArray] | None = None
        self.lifetimes_data_quality: DataQualityProfile | None = None
        self.lifetime_notes: str | None = None
        self.lifetime_reference_code: str | None = None

        self.capacity_to_activity: dict[CANOEFuel, RegionalValuesArray] | None = None
        self.c2a_units: str | None = None

    def set_annual(self, annual: int = 1):
        self.annual = annual
        return self

    def with_lifetimes(
        self,
        lifetimes: dict[CANOEFuel, RegionalValuesArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        self.lifetimes = lifetimes
        self.lifetimes_data_quality = data_quality
        self.lifetime_notes = notes
        self.lifetime_reference_code = reference_code
        return self

    def with_capacity_to_activity(
        self,
        capacity_to_activity: dict[CANOEFuel, RegionalValuesArray],
        units: str | None = None,
    ):
        self.capacity_to_activity = capacity_to_activity
        self.c2a_units = units
        return self

    def build(self, db_conn: Connection):
        # Build technologies
        for fuel in self.fuels:
            tech_name = f"{self.sector.get_tag()}_{self.demand_short_name}_{fuel.value}{self.capacity_scope_str}"
            tech_desc = f"{fuel.get_desc_name()} {self.capacity_scope_str} for {self.sector.name} sector"

            # Tech table
            technology = Technology(
                tech=tech_name,
                flag=self.tech_flag,
                description=tech_desc,
                data_id=self.data_id.get_dataset_code(),
                annual=self.annual,
            )
            sql, params = Technology.to_insert_or_ignore_sql(technology)
            write_label(db_conn, technology)
            db_conn.execute(sql, params)

            # Lifetimes
            if self.lifetimes:
                records = self.lifetimes[fuel].to_records()
                lifetimes = [
                    LifetimeTech(
                        region=row.region.short(),
                        tech=tech_name,
                        lifetime=np.round(row.value),
                        units="year",
                        notes=self.lifetime_notes
                        if i == 0 or not self.notes_only_on_first
                        else None,
                        data_source=self.lifetime_reference_code
                        if i == 0 or not self.reference_only_on_first
                        else None,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                        **(
                            self.lifetimes_data_quality.as_kwargs()
                            if self.lifetimes_data_quality and i == 0
                            else {}
                        ),
                    )
                    for i, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = LifetimeTech.bulk_insert_or_ignore_sql(
                    lifetimes, include_nulls=True
                )
                db_conn.executemany(sql, params)

            # C2A
            if self.capacity_to_activity:
                records = self.capacity_to_activity[fuel].to_records()
                capacity_to_activity = [
                    CapacityToActivity(
                        region=row.region.short(),
                        tech=tech_name,
                        c2a=row.value,
                        units=self.c2a_units,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                    )
                    for _, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = CapacityToActivity.bulk_insert_or_ignore_sql(
                    capacity_to_activity, include_nulls=True
                )
                db_conn.executemany(sql, params)

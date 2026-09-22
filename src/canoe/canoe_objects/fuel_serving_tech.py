from sqlite3 import Connection

import numpy as np
import pandas as pd
from canoe_schema.v4_0 import (
    CapacityToActivity,
    Commodity,
    CommodityTypeCode,
    CostFixed,
    Efficiency,
    ExistingCapacity,
    LifetimeTech,
    LimitAnnualCapacityFactor,
    OperatorCode,
    Technology,
    TechnologyTypeCode,
)

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.canoe_objects.technology import RegionVintageArray, RegionVintagePeriodArray
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_fuel_commodity_in_sector,
)


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
        short_desc: str,
        fuels: list[CANOEFuel],
        fuel_import_flag: dict[CANOEFuel, CommodityTypeCode],
        output_commodity_name: str,
        data_id: DatasetIdentifier,
        capacity_scope: TechnologyCapacityScope | None = None,
        tech_flag: TechnologyTypeCode = TechnologyTypeCode.P,
        include_region_in_data_id: bool = True,
        notes_only_on_first: bool = True,
        reference_only_on_first: bool = True,
    ) -> None:
        self.tech_flag: TechnologyTypeCode = tech_flag
        self.short_desc: str = short_desc
        self.sector: CANOESector = sector
        self.fuels: list[CANOEFuel] = fuels
        self.fuel_import_flag: dict[CANOEFuel, CommodityTypeCode] = fuel_import_flag
        self.output_commodity_name: str = output_commodity_name
        self.data_id: DatasetIdentifier = data_id
        self.include_region_in_data_id: bool = include_region_in_data_id
        self.capacity_scope: TechnologyCapacityScope | None = capacity_scope
        self.capacity_scope_str: str = (
            f"-{capacity_scope.value}" if capacity_scope else ""
        )
        self.notes_only_on_first: bool = notes_only_on_first
        self.reference_only_on_first: bool = reference_only_on_first

        # Check that for each fuel, the import flag exists
        for fuel in self.fuels:
            assert fuel in self.fuel_import_flag

        self.annual: int = 0

        # Set-able parameters
        # -------------------
        # Lifetimes
        self.lifetimes: dict[CANOEFuel, RegionalValuesArray] | None = None
        self.lifetimes_data_quality: DataQualityProfile | None = None
        self.lifetime_notes: str | None = None
        self.lifetime_reference_code: str | None = None

        # Efficiencies
        self.efficiencies: dict[CANOEFuel, RegionVintageArray] | None = None
        self.efficiency_notes: str | None = None
        self.efficiency_reference_code: str | None = None
        self.efficiency_data_quality: DataQualityProfile | None = None

        # Existing capacities
        self.existing_capacities: dict[CANOEFuel, RegionVintageArray] | None = None
        self.exs_cap_notes: str | None = None
        self.exs_cap_reference_code: str | None = None
        self.exs_cap_data_quality: DataQualityProfile | None = None
        self.exs_cap_units: str | None = None

        # Capacity to activity
        self.capacity_to_activity: dict[CANOEFuel, RegionalValuesArray] | None = None
        self.c2a_units: str | None = None

        # Fixed costs
        self.fixed_costs: dict[CANOEFuel, RegionVintagePeriodArray] | None = None
        self.fixed_costs_notes: str | None = None
        self.fixed_costs_reference_code: str | None = None
        self.fixed_costs_data_quality: DataQualityProfile | None = None
        self.fixed_costs_units: str | None = None

        # Capacity factors
        self.limit_annual_capacity_factors: (
            dict[CANOEFuel, RegionVintageArray] | None
        ) = None
        self.lacf_operator: OperatorCode | None = None
        self.limit_acf_notes: str | None = None
        self.limit_acf_data_quality: DataQualityProfile | None = None
        self.limit_acf_reference_code: str | None = None
        self.limit_acf_units: str | None = None

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

    def with_efficiencies(
        self,
        efficiencies: dict[CANOEFuel, RegionVintageArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        self.efficiencies = efficiencies
        self.efficiency_notes = notes
        self.efficiency_data_quality = data_quality
        self.efficiency_reference_code = reference_code
        return self

    def with_existing_capacities(
        self,
        existing_capacities: dict[CANOEFuel, RegionVintageArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.existing_capacities = existing_capacities
        self.exs_cap_notes = notes
        self.exs_cap_data_quality = data_quality
        self.exs_cap_reference_code = reference_code
        self.exs_cap_units = units
        return self

    def with_fixed_costs(
        self,
        fixed_costs: dict[CANOEFuel, RegionVintagePeriodArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.fixed_costs = fixed_costs
        self.fixed_costs_notes = notes
        self.fixed_costs_data_quality = data_quality
        self.fixed_costs_reference_code = reference_code
        self.fixed_costs_units = units
        return self

    def with_limit_annual_capacity_factor(
        self,
        capacity_factors: dict[CANOEFuel, RegionVintageArray],
        operator: OperatorCode,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.limit_annual_capacity_factors = capacity_factors
        self.lacf_operator = operator
        self.limit_acf_notes = notes
        self.limit_acf_data_quality = data_quality
        self.limit_acf_reference_code = reference_code
        self.limit_acf_units = units
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
            tech_name = f"{self.sector.get_tag()}_{self.short_desc}_{fuel.value}{self.capacity_scope_str}"
            tech_desc = f"{fuel.get_desc_name()} {self.capacity_scope_str} for {self.sector.name} sector"
            input_fuel_commodity_name = get_fuel_commodity_in_sector(self.sector, fuel)

            # Register fuel Commodity
            commodity = Commodity(
                name=input_fuel_commodity_name,
                flag=self.fuel_import_flag[fuel],
                description=f"{fuel.get_desc_name()} fuel for {self.sector.name} sector",
                data_id=self.data_id.get_dataset_code(),
            )
            sql, params = Commodity.to_insert_or_ignore_sql(commodity)
            write_label(db_conn, commodity)
            db_conn.execute(sql, params)

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

            # Efficiency
            if self.efficiencies:
                records = self.efficiencies[fuel].to_records()
                efficiencies = [
                    Efficiency(
                        region=row.region.short(),
                        input_comm=input_fuel_commodity_name,
                        tech=tech_name,
                        vintage=row.vintage,
                        output_comm=self.output_commodity_name,
                        efficiency=row.value,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                        notes=self.efficiency_notes
                        if i == 0 or not self.notes_only_on_first
                        else None,
                        data_source=self.efficiency_reference_code
                        if i == 0 or not self.reference_only_on_first
                        else None,
                        **(
                            self.efficiency_data_quality.as_kwargs()
                            if self.efficiency_data_quality and i == 0
                            else {}
                        ),
                    )
                    for i, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = Efficiency.bulk_insert_or_ignore_sql(
                    efficiencies, include_nulls=True
                )
                db_conn.executemany(sql, params)

            # Existing capacities
            if self.existing_capacities:
                records = self.existing_capacities[fuel].to_records()
                efficiencies = [
                    ExistingCapacity(
                        region=row.region.short(),
                        tech=tech_name,
                        vintage=row.vintage,
                        units=self.exs_cap_units,
                        capacity=row.value,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                        notes=self.exs_cap_notes
                        if i == 0 or not self.notes_only_on_first
                        else None,
                        data_source=self.exs_cap_reference_code
                        if i == 0 or not self.reference_only_on_first
                        else None,
                        **(
                            self.exs_cap_data_quality.as_kwargs()
                            if self.exs_cap_data_quality and i == 0
                            else {}
                        ),
                    )
                    for i, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = ExistingCapacity.bulk_insert_or_ignore_sql(
                    efficiencies, include_nulls=True
                )
                db_conn.executemany(sql, params)

            # Fixed costs
            if self.fixed_costs:
                records = self.fixed_costs[fuel].to_records()
                fixed_costs = [
                    CostFixed(
                        region=row.region.short(),
                        period=row.period,
                        tech=tech_name,
                        vintage=row.vintage,
                        cost=row.value,
                        units=self.fixed_costs_units,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                        notes=self.fixed_costs_notes
                        if i == 0 or not self.notes_only_on_first
                        else None,
                        data_source=self.fixed_costs_reference_code
                        if i == 0 or not self.reference_only_on_first
                        else None,
                        **(
                            self.fixed_costs_data_quality.as_kwargs()
                            if self.fixed_costs_data_quality and i == 0
                            else {}
                        ),
                    )
                    for i, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = CostFixed.bulk_insert_or_ignore_sql(
                    fixed_costs, include_nulls=True
                )
                db_conn.executemany(sql, params)

            # Existing capacities
            if self.limit_annual_capacity_factors:
                records = self.limit_annual_capacity_factors[fuel].to_records()
                efficiencies = [
                    LimitAnnualCapacityFactor(
                        region=row.region.short(),
                        tech_or_group=tech_name,
                        vintage=row.vintage,
                        operator=self.lacf_operator or OperatorCode.LE,
                        output_comm=self.output_commodity_name,
                        factor=row.value,
                        data_id=self.data_id.get_dataset_code(
                            province=row.region
                            if self.include_region_in_data_id
                            else None
                        ),
                        notes=self.limit_acf_notes
                        if i == 0 or not self.notes_only_on_first
                        else None,
                        data_source=self.limit_acf_reference_code
                        if i == 0 or not self.reference_only_on_first
                        else None,
                        **(
                            self.limit_acf_data_quality.as_kwargs()
                            if self.limit_acf_data_quality and i == 0
                            else {}
                        ),
                    )
                    for i, row in pd.DataFrame(records).iterrows()
                ]
                sql, params = LimitAnnualCapacityFactor.bulk_insert_or_ignore_sql(
                    efficiencies, include_nulls=True
                )
                db_conn.executemany(sql, params)

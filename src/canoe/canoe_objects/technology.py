from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any

import numpy as np
from canoe_schema.v4_0 import (
    CapacityToActivity,
    CostFixed,
    Efficiency,
    ExistingCapacity,
    LifetimeTech,
    LimitAnnualCapacityFactor,
    LimitTechInputSplit,
    LimitTechInputSplitAnnual,
    OperatorCode,
    SectorLabel,
    Technology,
    TechnologyTypeCode,
)

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.parameter import Parameter, ParameterMetadata, RowOptions
from canoe.common import CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import DatasetIdentifier


@dataclass(frozen=True)
class InputSplit:
    parameter: Parameter[RegionPeriodArray]
    operator: OperatorCode
    annual: bool


@dataclass(frozen=True)
class CapacityFactorLimit:
    parameter: Parameter[RegionVintageArray]
    operator: OperatorCode


class TechnologyEntity:
    """
    A single technology: one row in `technology`, one output commodity and any
    number of input commodities (one per `with_efficiency` call).

    Parameters are dense labeled arrays; `build` writes one row per non-NaN cell.
    Input and output commodities must already exist in the database.

    `validate` (called by `build`) catches inconsistencies Temoa would otherwise
    silently drop or turn into an infeasible model:
    - the technology has no inputs, or non-positive efficiencies
    - a parameter was set but has no values (all NaN)
    - input splits for commodities that are not inputs, or adding up to more than 1
    - existing capacity for a (region, vintage) without any efficiency
    - fixed costs for periods before the vintage or after the end of its lifetime
    """

    def __init__(
        self,
        name: str,
        output_commodity: str,
        data_id: DatasetIdentifier,
        description: str | None = None,
        sector: CANOESector | None = None,
        flag: TechnologyTypeCode = TechnologyTypeCode.P,
        include_region_in_data_id: bool = True,
        notes_only_on_first: bool = True,
        reference_only_on_first: bool = True,
    ) -> None:
        self.name: str = name
        self.output_commodity: str = output_commodity
        self.description: str | None = description
        self.sector: CANOESector | None = sector
        self.flag: TechnologyTypeCode = flag
        self.row_options: RowOptions = RowOptions(
            data_id=data_id,
            include_region_in_data_id=include_region_in_data_id,
            notes_only_on_first=notes_only_on_first,
            reference_only_on_first=reference_only_on_first,
        )

        self.annual: int = 0
        self.unlimited_capacity: int = 0

        # Set-able parameters
        # -------------------
        # input commodity -> efficiencies
        self.efficiencies: dict[str, Parameter[RegionVintageArray]] = {}
        # input commodity -> input split
        self.input_splits: dict[str, InputSplit] = {}
        self.lifetime: Parameter[RegionalValuesArray] | None = None
        self.capacity_to_activity: Parameter[RegionalValuesArray] | None = None
        self.existing_capacity: Parameter[RegionVintageArray] | None = None
        self.fixed_cost: Parameter[RegionVintagePeriodArray] | None = None
        self.capacity_factor_limit: CapacityFactorLimit | None = None

    @property
    def inputs(self) -> list[str]:
        return list(self.efficiencies)

    def set_annual(self, annual: bool = True):
        self.annual = int(annual)
        return self

    def set_unlimited_capacity(self, unlimited: bool = True):
        self.unlimited_capacity = int(unlimited)
        return self

    def with_efficiency(
        self,
        input_commodity: str,
        efficiencies: RegionVintageArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """Adds `input_commodity` as an input of this technology"""
        self.efficiencies[input_commodity] = Parameter(
            efficiencies,
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_input_split(
        self,
        input_commodity: str,
        splits: RegionPeriodArray,
        operator: OperatorCode = OperatorCode.LE,
        annual: bool = True,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        """
        Limit the share of `input_commodity` in the technology's inputs.
        `annual` uses `limit_tech_input_split_annual` instead of `limit_tech_input_split`.
        """
        self.input_splits[input_commodity] = InputSplit(
            Parameter(splits, ParameterMetadata(notes, reference_code, data_quality)),
            operator,
            annual,
        )
        return self

    def with_lifetime(
        self,
        lifetimes: RegionalValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = "year",
    ):
        """Lifetimes are rounded to whole years when written"""
        self.lifetime = Parameter(
            lifetimes, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_capacity_to_activity(
        self,
        capacity_to_activity: RegionalValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.capacity_to_activity = Parameter(
            capacity_to_activity,
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_existing_capacity(
        self,
        existing_capacity: RegionVintageArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.existing_capacity = Parameter(
            existing_capacity,
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_fixed_cost(
        self,
        fixed_cost: RegionVintagePeriodArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.fixed_cost = Parameter(
            fixed_cost, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_limit_annual_capacity_factor(
        self,
        capacity_factors: RegionVintageArray,
        operator: OperatorCode = OperatorCode.LE,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        self.capacity_factor_limit = CapacityFactorLimit(
            Parameter(
                capacity_factors,
                ParameterMetadata(notes, reference_code, data_quality),
            ),
            operator,
        )
        return self

    def validate(self) -> None:
        """Raises ValueError on inconsistent parameters, see class docstring"""
        if not self.efficiencies:
            raise ValueError(f"Technology {self.name} has no inputs (no efficiencies)")

        # Parameters that were set but have no values (all NaN)
        parameters: dict[str, Parameter[Any] | None] = {
            **{f"efficiency ({i})": p for i, p in self.efficiencies.items()},
            **{f"input split ({i})": s.parameter for i, s in self.input_splits.items()},
            "lifetime": self.lifetime,
            "capacity to activity": self.capacity_to_activity,
            "existing capacity": self.existing_capacity,
            "fixed cost": self.fixed_cost,
            "annual capacity factor limit": self.capacity_factor_limit.parameter
            if self.capacity_factor_limit
            else None,
        }
        for parameter_name, parameter in parameters.items():
            if parameter is not None and not parameter.values.to_records():
                raise ValueError(
                    f"Technology {self.name}: {parameter_name} was set but has no values"
                )

        # (region, vintage) cells with at least one efficiency
        efficiency_cells: set[tuple[CANOEProvince, int]] = set()
        for input_commodity, efficiency in self.efficiencies.items():
            for record in efficiency.values.to_records():
                if record["value"] <= 0:
                    raise ValueError(
                        f"Technology {self.name}: non-positive efficiency {record['value']} "
                        + f"for input {input_commodity} at {record['region']}, {record['vintage']}"
                    )
                efficiency_cells.add((record["region"], record["vintage"]))

        # Input splits
        not_inputs = set(self.input_splits) - set(self.efficiencies)
        if not_inputs:
            raise ValueError(
                f"Technology {self.name}: input splits for commodities that are not inputs: {not_inputs}"
            )
        split_totals: dict[tuple[CANOEProvince, int], float] = {}
        for split in self.input_splits.values():
            for record in split.parameter.values.to_records():
                key = (record["region"], record["period"])
                split_totals[key] = split_totals.get(key, 0.0) + record["value"]
        for (region, period), total in split_totals.items():
            if total > 1 + 1e-9:
                raise ValueError(
                    f"Technology {self.name}: input splits add up to {total} (> 1) "
                    + f"at {region}, {period}"
                )

        # Existing capacity
        if self.existing_capacity:
            for record in self.existing_capacity.values.to_records():
                if (record["region"], record["vintage"]) not in efficiency_cells:
                    raise ValueError(
                        f"Technology {self.name}: existing capacity without efficiency "
                        + f"at {record['region']}, {record['vintage']}"
                    )

        # Fixed costs
        if self.fixed_cost:
            lifetimes: dict[CANOEProvince, float] = (
                {
                    r["region"]: np.round(r["value"])
                    for r in self.lifetime.values.to_records()
                }
                if self.lifetime
                else {}
            )
            for record in self.fixed_cost.values.to_records():
                region = record["region"]
                vintage = record["vintage"]
                period = record["period"]
                if period < vintage:
                    raise ValueError(
                        f"Technology {self.name}: fixed cost for period {period} "
                        + f"before vintage {vintage} at {region}"
                    )
                if region in lifetimes and vintage + lifetimes[region] <= period:
                    raise ValueError(
                        f"Technology {self.name}: fixed cost for period {period} after "
                        + f"the end of life of vintage {vintage} at {region}"
                    )

    def build(self, db_conn: Connection):
        self.validate()
        options = self.row_options

        # Sector label
        if self.sector is not None:
            write_label(db_conn, self.sector)

        # Technology table
        technology = Technology(
            tech=self.name,
            flag=self.flag,
            sector=self.sector,
            description=self.description,
            unlim_cap=self.unlimited_capacity,
            annual=self.annual,
            data_id=options.dataset_code(),
        )
        sql, params = Technology.to_insert_or_ignore_sql(technology)
        write_label(db_conn, technology)
        db_conn.execute(sql, params)

        # Lifetimes
        if self.lifetime:
            meta = self.lifetime.metadata
            lifetimes = [
                LifetimeTech(
                    region=row["region"].short(),
                    tech=self.name,
                    lifetime=np.round(row["value"]),
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.lifetime.values.to_records())
            ]
            sql, params = LifetimeTech.bulk_insert_or_ignore_sql(
                lifetimes, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # C2A
        if self.capacity_to_activity:
            meta = self.capacity_to_activity.metadata
            capacity_to_activity = [
                CapacityToActivity(
                    region=row["region"].short(),
                    tech=self.name,
                    c2a=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.capacity_to_activity.values.to_records())
            ]
            sql, params = CapacityToActivity.bulk_insert_or_ignore_sql(
                capacity_to_activity, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Efficiencies (one set of rows per input)
        for input_commodity, efficiency in self.efficiencies.items():
            meta = efficiency.metadata
            efficiencies = [
                Efficiency(
                    region=row["region"].short(),
                    input_comm=input_commodity,
                    tech=self.name,
                    vintage=row["vintage"],
                    output_comm=self.output_commodity,
                    efficiency=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(efficiency.values.to_records())
            ]
            sql, params = Efficiency.bulk_insert_or_ignore_sql(
                efficiencies, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Existing capacities
        if self.existing_capacity:
            meta = self.existing_capacity.metadata
            existing_capacities = [
                ExistingCapacity(
                    region=row["region"].short(),
                    tech=self.name,
                    vintage=row["vintage"],
                    capacity=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.existing_capacity.values.to_records())
            ]
            sql, params = ExistingCapacity.bulk_insert_or_ignore_sql(
                existing_capacities, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Fixed costs
        if self.fixed_cost:
            meta = self.fixed_cost.metadata
            fixed_costs = [
                CostFixed(
                    region=row["region"].short(),
                    period=row["period"],
                    tech=self.name,
                    vintage=row["vintage"],
                    cost=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.fixed_cost.values.to_records())
            ]
            sql, params = CostFixed.bulk_insert_or_ignore_sql(
                fixed_costs, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Annual capacity factor limits
        if self.capacity_factor_limit:
            limit = self.capacity_factor_limit
            meta = limit.parameter.metadata
            capacity_factors = [
                LimitAnnualCapacityFactor(
                    region=row["region"].short(),
                    tech_or_group=self.name,
                    vintage=row["vintage"],
                    output_comm=self.output_commodity,
                    operator=limit.operator,
                    factor=row["value"],
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(limit.parameter.values.to_records())
            ]
            sql, params = LimitAnnualCapacityFactor.bulk_insert_or_ignore_sql(
                capacity_factors, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Input splits (one set of rows per input)
        for input_commodity, split in self.input_splits.items():
            meta = split.parameter.metadata
            split_model = (
                LimitTechInputSplitAnnual if split.annual else LimitTechInputSplit
            )
            input_splits = [
                split_model(
                    region=row["region"].short(),
                    period=row["period"],
                    input_comm=input_commodity,
                    tech=self.name,
                    operator=split.operator,
                    proportion=row["value"],
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(split.parameter.values.to_records())
            ]
            sql, params = split_model.bulk_insert_or_ignore_sql(
                input_splits, include_nulls=True
            )
            db_conn.executemany(sql, params)

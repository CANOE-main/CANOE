from dataclasses import dataclass
from enum import StrEnum
from sqlite3 import Connection
from typing import Any

from canoe_schema.v4_0 import (
    Commodity,
    CommodityTypeCode,
    OperatorCode,
    TechnologyTypeCode,
)

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.canoe_objects.parameter import ParameterMetadata
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOESector, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_fuel_commodity_in_sector,
)


class FuelGrouping(StrEnum):
    # One technology per fuel, each with a single input
    PerFuel = "per_fuel"
    # A single technology with every fuel as an input
    Shared = "shared"


@dataclass(frozen=True)
class TechnologyParameter[A: LabeledArray]:
    """
    A technology-level parameter (lifetime, capacity, costs, ...).
    `values` is a dict by fuel for `FuelGrouping.PerFuel`, or a single array for
    the one technology of `FuelGrouping.Shared`.
    """

    values: dict[CANOEFuel, A] | A
    metadata: ParameterMetadata

    def for_technology(self, fuel: CANOEFuel | None) -> A:
        if isinstance(self.values, dict):
            assert fuel is not None, (
                "Attempted to retrieve values of a per-fuel parameter, but fuel is None"
            )
            return self.values[fuel]
        return self.values


@dataclass(frozen=True)
class InputParameter[A: LabeledArray]:
    """An input-level parameter (efficiency, input split), always by fuel"""

    values: dict[CANOEFuel, A]
    metadata: ParameterMetadata


class FuelServingTechnologyEntity:
    """
    Builds technologies that serve an end-use demand using various input fuels.

    With `FuelGrouping.PerFuel` there is one technology per fuel
    (`{sector}_{short_desc}_{fuel}{scope}`) and every parameter is given by fuel.
    With `FuelGrouping.Shared` there is a single technology (`{sector}_{short_desc}{scope}`)
    taking all fuels as inputs: efficiencies and input splits are still given by fuel,
    technology-level parameters (lifetimes, capacities, costs, ...) as a single array.
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
        grouping: FuelGrouping = FuelGrouping.PerFuel,
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
        self.grouping: FuelGrouping = grouping
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
        self.unlimited_capacity: int = 0

        # Set-able parameters
        # -------------------
        self.efficiencies: InputParameter[RegionVintageArray] | None = None
        self.input_splits: InputParameter[RegionPeriodArray] | None = None
        self.input_split_operator: OperatorCode = OperatorCode.LE
        self.lifetimes: TechnologyParameter[RegionalValuesArray] | None = None
        self.capacity_to_activity: TechnologyParameter[RegionalValuesArray] | None = (
            None
        )
        self.existing_capacities: TechnologyParameter[RegionVintageArray] | None = None
        self.fixed_costs: TechnologyParameter[RegionVintagePeriodArray] | None = None
        self.limit_annual_capacity_factors: (
            TechnologyParameter[RegionVintageArray] | None
        ) = None
        self.lacf_operator: OperatorCode = OperatorCode.LE

    def set_annual(self, annual: int = 1):
        self.annual = annual
        return self

    def set_unlimited_capacity(self, unlimited: int = 1):
        self.unlimited_capacity = unlimited
        return self

    def with_lifetimes(
        self,
        lifetimes: dict[CANOEFuel, RegionalValuesArray] | RegionalValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = "year",
    ):
        self.lifetimes = TechnologyParameter(
            self._check_technology_values(lifetimes, "lifetimes"),
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_efficiencies(
        self,
        efficiencies: dict[CANOEFuel, RegionVintageArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.efficiencies = InputParameter(
            self._check_input_values(efficiencies, "efficiencies"),
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_input_splits(
        self,
        input_splits: dict[CANOEFuel, RegionPeriodArray],
        operator: OperatorCode = OperatorCode.LE,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        """Annual input splits. Only meaningful for `FuelGrouping.Shared`."""
        if self.grouping != FuelGrouping.Shared:
            raise ValueError(
                "Input splits need FuelGrouping.Shared: per-fuel technologies have a single input"
            )
        self.input_splits = InputParameter(
            input_splits, ParameterMetadata(notes, reference_code, data_quality)
        )
        self.input_split_operator = operator
        return self

    def with_existing_capacities(
        self,
        existing_capacities: dict[CANOEFuel, RegionVintageArray] | RegionVintageArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.existing_capacities = TechnologyParameter(
            self._check_technology_values(existing_capacities, "existing_capacities"),
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_fixed_costs(
        self,
        fixed_costs: dict[CANOEFuel, RegionVintagePeriodArray]
        | RegionVintagePeriodArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        self.fixed_costs = TechnologyParameter(
            self._check_technology_values(fixed_costs, "fixed_costs"),
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_limit_annual_capacity_factor(
        self,
        capacity_factors: dict[CANOEFuel, RegionVintageArray] | RegionVintageArray,
        operator: OperatorCode,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        self.limit_annual_capacity_factors = TechnologyParameter(
            self._check_technology_values(capacity_factors, "capacity_factors"),
            ParameterMetadata(notes, reference_code, data_quality),
        )
        self.lacf_operator = operator
        return self

    def with_capacity_to_activity(
        self,
        capacity_to_activity: dict[CANOEFuel, RegionalValuesArray]
        | RegionalValuesArray,
        units: str | None = None,
    ):
        self.capacity_to_activity = TechnologyParameter(
            self._check_technology_values(capacity_to_activity, "capacity_to_activity"),
            ParameterMetadata(units=units),
        )
        return self

    def to_technology_entities(self) -> list[TechnologyEntity]:
        """The technologies this entity builds, one per fuel or a single shared one"""
        tag = self.sector.get_tag()
        scope = self.capacity_scope_str
        scope_desc = f" {scope}" if scope else ""

        if self.grouping == FuelGrouping.PerFuel:
            technologies: list[TechnologyEntity] = []
            for fuel in self.fuels:
                technologies.append(
                    self._technology_entity(
                        name=f"{tag}_{self.short_desc}_{fuel.value}{scope}",
                        description=f"{fuel.get_desc_name()}{scope_desc} for {self.sector.name} sector",
                        fuels=[fuel],
                        fuel_key=fuel,
                    )
                )
            return technologies

        fuel_names = ", ".join(fuel.get_desc_name() for fuel in self.fuels)
        shared_technology = self._technology_entity(
            name=f"{tag}_{self.short_desc}{scope}",
            description=f"{fuel_names}{scope_desc} for {self.sector.name} sector",
            fuels=self.fuels,
            fuel_key=None,
        )
        return [shared_technology]

    def build(self, db_conn: Connection):
        # Register fuel commodities
        for fuel in self.fuels:
            commodity = Commodity(
                name=get_fuel_commodity_in_sector(self.sector, fuel),
                flag=self.fuel_import_flag[fuel],
                description=f"{fuel.get_desc_name()} fuel for {self.sector.name} sector",
                data_id=self.data_id.get_dataset_code(),
            )
            sql, params = Commodity.to_insert_or_ignore_sql(commodity)
            write_label(db_conn, commodity)
            db_conn.execute(sql, params)

        # Build technologies
        for technology in self.to_technology_entities():
            technology.build(db_conn)

    def _technology_entity(
        self,
        name: str,
        description: str,
        fuels: list[CANOEFuel],
        fuel_key: CANOEFuel | None,
    ) -> TechnologyEntity:
        """
        `fuel_key` selects the technology-level values for a per-fuel technology,
        None for the shared technology.
        """
        technology = (
            TechnologyEntity(
                name=name,
                output_commodity=self.output_commodity_name,
                data_id=self.data_id,
                description=description,
                sector=self.sector,
                flag=self.tech_flag,
                include_region_in_data_id=self.include_region_in_data_id,
                notes_only_on_first=self.notes_only_on_first,
                reference_only_on_first=self.reference_only_on_first,
            )
            .set_annual(bool(self.annual))
            .set_unlimited_capacity(bool(self.unlimited_capacity))
        )

        for fuel in fuels:
            input_commodity = get_fuel_commodity_in_sector(self.sector, fuel)
            if self.efficiencies:
                technology.with_efficiency(
                    input_commodity,
                    self.efficiencies.values[fuel],
                    **_metadata_kwargs(self.efficiencies.metadata),
                )
            if self.input_splits and fuel in self.input_splits.values:
                meta = self.input_splits.metadata
                technology.with_input_split(
                    input_commodity,
                    self.input_splits.values[fuel],
                    operator=self.input_split_operator,
                    notes=meta.notes,
                    data_quality=meta.data_quality,
                    reference_code=meta.reference_code,
                )

        if self.lifetimes:
            technology.with_lifetime(
                self.lifetimes.for_technology(fuel_key),
                **_metadata_kwargs(self.lifetimes.metadata),
            )
        if self.capacity_to_activity:
            technology.with_capacity_to_activity(
                self.capacity_to_activity.for_technology(fuel_key),
                **_metadata_kwargs(self.capacity_to_activity.metadata),
            )
        if self.existing_capacities:
            technology.with_existing_capacity(
                self.existing_capacities.for_technology(fuel_key),
                **_metadata_kwargs(self.existing_capacities.metadata),
            )
        if self.fixed_costs:
            technology.with_fixed_cost(
                self.fixed_costs.for_technology(fuel_key),
                **_metadata_kwargs(self.fixed_costs.metadata),
            )
        if self.limit_annual_capacity_factors:
            meta = self.limit_annual_capacity_factors.metadata
            technology.with_limit_annual_capacity_factor(
                self.limit_annual_capacity_factors.for_technology(fuel_key),
                operator=self.lacf_operator,
                notes=meta.notes,
                data_quality=meta.data_quality,
                reference_code=meta.reference_code,
            )
        return technology

    def _check_technology_values[A: LabeledArray](
        self, values: dict[CANOEFuel, A] | A, name: str
    ) -> dict[CANOEFuel, A] | A:
        if self.grouping == FuelGrouping.PerFuel:
            if not isinstance(values, dict):
                raise TypeError(
                    f"{name}: FuelGrouping.PerFuel expects a dict of values by fuel"
                )
            return self._check_input_values(values, name)
        if not isinstance(values, LabeledArray):
            raise TypeError(
                f"{name}: FuelGrouping.Shared expects a single array for the shared technology"
            )
        return values

    def _check_input_values[A: LabeledArray](
        self, values: dict[CANOEFuel, A], name: str
    ) -> dict[CANOEFuel, A]:
        missing = set(self.fuels) - set(values)
        if missing:
            raise ValueError(f"{name}: missing values for fuels {missing}")
        return values


def _metadata_kwargs(metadata: ParameterMetadata) -> dict[str, Any]:
    return {
        "notes": metadata.notes,
        "data_quality": metadata.data_quality,
        "reference_code": metadata.reference_code,
        "units": metadata.units,
    }

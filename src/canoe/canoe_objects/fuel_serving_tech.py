"""
Technologies that serve an end-use demand from a set of input fuels.

`FuelServingTechnologyEntity` registers the sector's fuel commodities and creates the
`TechnologyEntity` objects that turn those fuels into the demand, either one per fuel
or a single shared one (see `FuelGrouping`).

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py` (data sets `COMDOC*`, regions ON/QC, periods 2020-2035,
commodity label `C_D_DOC` for the demand).
"""

from dataclasses import dataclass
from enum import StrEnum
from sqlite3 import Connection
from typing import Any

from canoe_schema.v4_0 import (
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
from canoe.canoe_objects.commodity import FuelCommodityEntity
from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.canoe_objects.parameter import ParameterMetadata
from canoe.canoe_objects.technology import InputEmissionFactor, TechnologyEntity
from canoe.common import CANOEFuel, CANOESector, DataQualityProfile
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_fuel_commodity_in_sector,
)


class FuelGrouping(StrEnum):
    """
    How a `FuelServingTechnologyEntity` maps fuels to technologies.

    - `PerFuel`: one technology per fuel, each with a single input. The model chooses
      the fuel mix, subject to each technology's capacity and costs.
    - `Shared`: a single technology with every fuel as an input. The fuel mix is
      controlled with input splits.
    """

    PerFuel = "per_fuel"
    """One technology per fuel, each with a single input."""

    Shared = "shared"
    """A single technology with every fuel as an input."""


@dataclass(frozen=True)
class TechnologyParameter[A: LabeledArray]:
    """
    A technology-level parameter (lifetime, capacity, costs, ...) and its metadata.

    Parameters
    ----------
    values : dict[CANOEFuel, LabeledArray] or LabeledArray
        One array per fuel for `FuelGrouping.PerFuel`, or a single array for the one
        technology of `FuelGrouping.Shared`.
    metadata : ParameterMetadata
        Notes, data source, data quality and units, shared by all technologies.
    """

    values: dict[CANOEFuel, A] | A
    metadata: ParameterMetadata

    def for_technology(self, fuel: CANOEFuel | None) -> A:
        """
        Values for the technology of `fuel` (per-fuel), or for the shared technology
        (`fuel` ignored).
        """
        if isinstance(self.values, dict):
            assert fuel is not None, (
                "Attempted to retrieve values of a per-fuel parameter, but fuel is None"
            )
            return self.values[fuel]
        return self.values


@dataclass(frozen=True)
class InputParameter[A: LabeledArray]:
    """
    An input-level parameter (efficiency, input split) and its metadata.

    Parameters
    ----------
    values : dict[CANOEFuel, LabeledArray]
        One array per fuel, whatever the grouping.
    metadata : ParameterMetadata
        Notes, data source, data quality and units, shared by all fuels.
    """

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

    The input of each fuel is the sector's fuel commodity
    (`get_fuel_commodity_in_sector`, e.g. `C_elc`), which `build` registers. The
    output commodity must already exist. Each `with_*` method maps to the
    `TechnologyEntity` method of the same name and takes the same optional metadata
    (`notes`, `data_quality`, `reference_code`, `units`), shared by all technologies.

    Parameters
    ----------
    sector : CANOESector
        Sector of the technologies and fuel commodities.
    short_desc : str
        Short description used in technology names, e.g. "SPH".
    fuels : list[CANOEFuel]
        Input fuels.
    fuel_import_flag : dict[CANOEFuel, CommodityTypeCode]
        Commodity type of each fuel commodity, e.g. physical (`p`) for electricity
        and annual (`a`) for fuels. Required for every fuel.
    output_commodity_name : str
        Commodity produced by the technologies (the demand).
    data_id : DatasetIdentifier
        Data set the rows belong to.
    capacity_scope : TechnologyCapacityScope, optional
        Appended to technology names, e.g. "-EXS" for existing capacity.
    grouping : FuelGrouping
        One technology per fuel (default) or a single shared one.
    tech_flag : TechnologyTypeCode
        Technology type, production (`p`) by default.
    include_region_in_data_id, notes_only_on_first, reference_only_on_first : bool
        How metadata is spread over rows, see `RowOptions`.

    Examples
    --------
    Existing electric and natural gas heating in Ontario, one technology per fuel:

    >>> from canoe.canoe_objects.array_types import RegionalValuesArray, RegionVintageArray
    >>> from canoe.common import CANOEProvince
    >>> regions = [CANOEProvince.ONTARIO]
    >>> fuels = [CANOEFuel.Electricity, CANOEFuel.NaturalGas]
    >>> heating = (
    ...     FuelServingTechnologyEntity(
    ...         sector=CANOESector.Commercial,
    ...         short_desc="DOC",
    ...         fuels=fuels,
    ...         fuel_import_flag={
    ...             CANOEFuel.Electricity: CommodityTypeCode.P,
    ...             CANOEFuel.NaturalGas: CommodityTypeCode.A,
    ...         },
    ...         output_commodity_name="C_D_DOC",
    ...         data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ...         capacity_scope=TechnologyCapacityScope.Existing,
    ...     )
    ...     .set_annual()
    ...     .with_efficiencies(
    ...         {
    ...             CANOEFuel.Electricity: RegionVintageArray(regions, [2020], fill=1.0),
    ...             CANOEFuel.NaturalGas: RegionVintageArray(regions, [2020], fill=0.8),
    ...         }
    ...     )
    ...     .with_existing_capacities(
    ...         {
    ...             CANOEFuel.Electricity: RegionVintageArray(regions, [2020], fill=30),
    ...             CANOEFuel.NaturalGas: RegionVintageArray(regions, [2020], fill=220),
    ...         },
    ...         units="PJ",
    ...     )
    ...     .with_lifetimes({fuel: RegionalValuesArray(regions, fill=20) for fuel in fuels})
    ... )
    >>> [technology.name for technology in heating.to_technology_entities()]
    ['C_DOC_ELC-EXS', 'C_DOC_NG-EXS']
    >>> heating.build(db)
    >>> db.execute("SELECT name, flag FROM commodity").fetchall()
    [('C_elc', 'p'), ('C_ng', 'a')]
    >>> db.execute("SELECT tech, input_comm, vintage, efficiency FROM efficiency").fetchall()
    [('C_DOC_ELC-EXS', 'C_elc', 2020, 1.0), ('C_DOC_NG-EXS', 'C_ng', 2020, 0.8)]
    >>> db.execute("SELECT tech, vintage, capacity, units FROM existing_capacity").fetchall()
    [('C_DOC_ELC-EXS', 2020, 30.0, 'PJ'), ('C_DOC_NG-EXS', 2020, 220.0, 'PJ')]

    Technology-level values must match the grouping:

    >>> heating.with_lifetimes(RegionalValuesArray(regions, fill=20))
    Traceback (most recent call last):
    ...
    TypeError: lifetimes: FuelGrouping.PerFuel expects a dict of values by fuel
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
        # emission commodity -> fuel -> emission factor
        self.input_emission_factors: dict[
            str, dict[CANOEFuel, InputEmissionFactor]
        ] = {}

    def set_annual(self, annual: int = 1):
        """Mark all technologies as annual, see `TechnologyEntity.set_annual`"""
        self.annual = annual
        return self

    def set_unlimited_capacity(self, unlimited: int = 1):
        """
        Mark all technologies as having unlimited capacity, see
        `TechnologyEntity.set_unlimited_capacity`
        """
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
        """
        Set the lifetimes (`lifetime_tech`), see `TechnologyEntity.with_lifetime`.

        Parameters
        ----------
        lifetimes : dict[CANOEFuel, RegionalValuesArray] or RegionalValuesArray
            Lifetime in years by region; by fuel for `PerFuel`, a single array for
            `Shared`.
        """
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
        """
        Set the efficiency of each fuel (`efficiency`), see
        `TechnologyEntity.with_efficiency`.

        Parameters
        ----------
        efficiencies : dict[CANOEFuel, RegionVintageArray]
            Output per unit of input by region and vintage, for every fuel (whatever
            the grouping).
        """
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
        """
        Set the annual share of each fuel in the shared technology's inputs
        (`limit_tech_input_split_annual`), see `TechnologyEntity.with_input_split`.

        Only for `FuelGrouping.Shared`: per-fuel technologies have a single input.
        Fuels missing from `input_splits` get no split.

        Parameters
        ----------
        input_splits : dict[CANOEFuel, RegionPeriodArray]
            Share (0-1) of each fuel by region and period.
        operator : OperatorCode
            Upper bound (`le`, default), lower bound (`ge`) or exact share (`e`).

        Raises
        ------
        ValueError
            If the grouping is not `FuelGrouping.Shared`.

        Examples
        --------
        A single technology serving a demand from electricity and natural gas, with
        unlimited capacity and the fuel mix fixed by input splits:

        >>> from canoe.canoe_objects.array_types import RegionPeriodArray, RegionVintageArray
        >>> from canoe.common import CANOEProvince
        >>> regions = [CANOEProvince.ONTARIO]
        >>> fuels = [CANOEFuel.Electricity, CANOEFuel.NaturalGas]
        >>> other = (
        ...     FuelServingTechnologyEntity(
        ...         sector=CANOESector.Commercial,
        ...         short_desc="DOC",
        ...         fuels=fuels,
        ...         fuel_import_flag={
        ...             CANOEFuel.Electricity: CommodityTypeCode.P,
        ...             CANOEFuel.NaturalGas: CommodityTypeCode.A,
        ...         },
        ...         output_commodity_name="C_D_DOC",
        ...         data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
        ...         grouping=FuelGrouping.Shared,
        ...     )
        ...     .set_annual()
        ...     .set_unlimited_capacity()
        ...     .with_efficiencies(
        ...         {fuel: RegionVintageArray(regions, [2025], fill=1.0) for fuel in fuels}
        ...     )
        ...     .with_input_splits(
        ...         {
        ...             CANOEFuel.Electricity: RegionPeriodArray(regions, [2025], fill=0.8),
        ...             CANOEFuel.NaturalGas: RegionPeriodArray(regions, [2025], fill=0.2),
        ...         }
        ...     )
        ... )
        >>> [technology.name for technology in other.to_technology_entities()]
        ['C_DOC']
        >>> other.build(db)
        >>> db.execute("SELECT tech, unlim_cap, annual FROM technology").fetchall()
        [('C_DOC', 1, 1)]
        >>> db.execute(
        ...     "SELECT tech, input_comm, proportion FROM limit_tech_input_split_annual"
        ... ).fetchall()
        [('C_DOC', 'C_elc', 0.8), ('C_DOC', 'C_ng', 0.2)]
        """
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
        """
        Set the existing capacities (`existing_capacity`), see
        `TechnologyEntity.with_existing_capacity`.

        Parameters
        ----------
        existing_capacities : dict[CANOEFuel, RegionVintageArray] or RegionVintageArray
            Installed capacity by region and vintage; by fuel for `PerFuel`, a single
            array for `Shared`.
        """
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
        """
        Set the fixed costs (`cost_fixed`), see `TechnologyEntity.with_fixed_cost`.

        Parameters
        ----------
        fixed_costs : dict[CANOEFuel, RegionVintagePeriodArray] or RegionVintagePeriodArray
            Cost by region, vintage and period; by fuel for `PerFuel`, a single array
            for `Shared`.
        """
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
        """
        Limit the annual capacity factors (`limit_annual_capacity_factor`), see
        `TechnologyEntity.with_limit_annual_capacity_factor`.

        Parameters
        ----------
        capacity_factors : dict[CANOEFuel, RegionVintageArray] or RegionVintageArray
            Capacity factor (0-1) by region and vintage; by fuel for `PerFuel`, a
            single array for `Shared`.
        operator : OperatorCode
            Upper bound (`le`), lower bound (`ge`) or exact factor (`e`).
        """
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
        """
        Set the capacity-to-activity ratios (`capacity_to_activity`), see
        `TechnologyEntity.with_capacity_to_activity`.

        Parameters
        ----------
        capacity_to_activity : dict[CANOEFuel, RegionalValuesArray] or RegionalValuesArray
            Ratio by region; by fuel for `PerFuel`, a single array for `Shared`.
        """
        self.capacity_to_activity = TechnologyParameter(
            self._check_technology_values(capacity_to_activity, "capacity_to_activity"),
            ParameterMetadata(units=units),
        )
        return self

    def with_input_emission_factors(
        self,
        emission_commodity: str,
        factors: dict[CANOEFuel, float | RegionVintageArray],
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """
        Emit `emission_commodity` per unit of each fuel consumed (`emission_activity`),
        see `TechnologyEntity.with_input_emission_factor`. Call once per emission.

        Parameters
        ----------
        emission_commodity : str
            Emission commodity, see `get_emission_commodity_name`.
        factors : dict[CANOEFuel, float or RegionVintageArray]
            Emissions per unit of fuel; fuels left out (e.g. electricity) do not emit.

        Examples
        --------
        >>> from canoe.canoe_objects.array_types import RegionVintageArray
        >>> from canoe.common import CANOEProvince
        >>> regions = [CANOEProvince.ONTARIO]
        >>> fuels = [CANOEFuel.Electricity, CANOEFuel.NaturalGas]
        >>> heating = (
        ...     FuelServingTechnologyEntity(
        ...         sector=CANOESector.Commercial,
        ...         short_desc="DOC",
        ...         fuels=fuels,
        ...         fuel_import_flag={
        ...             CANOEFuel.Electricity: CommodityTypeCode.P,
        ...             CANOEFuel.NaturalGas: CommodityTypeCode.A,
        ...         },
        ...         output_commodity_name="C_D_DOC",
        ...         data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
        ...     )
        ...     .with_efficiencies(
        ...         {fuel: RegionVintageArray(regions, [2025], fill=0.8) for fuel in fuels}
        ...     )
        ...     .with_input_emission_factors("co2", {CANOEFuel.NaturalGas: 50.0}, units="kt/PJ")
        ... )
        >>> heating.build(db)
        >>> db.execute("SELECT tech, emis_comm, activity FROM emission_activity").fetchall()
        [('C_DOC_NG', 'co2', 62.5)]
        """
        not_fuels = set(factors) - set(self.fuels)
        if not_fuels:
            raise ValueError(
                f"{emission_commodity} emission factors for fuels that are not inputs: {not_fuels}"
            )
        metadata = ParameterMetadata(notes, reference_code, data_quality, units)
        self.input_emission_factors[emission_commodity] = {
            fuel: InputEmissionFactor(factor, metadata)
            for fuel, factor in factors.items()
        }
        return self

    def to_technology_entities(self) -> list[TechnologyEntity]:
        """
        The technologies this entity builds, one per fuel or a single shared one.

        Useful to inspect (or validate) the technologies without writing them;
        `build` writes exactly these.
        """
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
        """
        Write the fuel commodities and the technologies to the database.

        Registers one `FuelCommodityEntity` per fuel, then builds each
        technology from `to_technology_entities` (see `TechnologyEntity.build`).

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.

        Raises
        ------
        ValueError
            If a technology fails `TechnologyEntity.validate`.
        """
        # Register fuel commodities
        for fuel in self.fuels:
            FuelCommodityEntity(
                sector=self.sector,
                fuel=fuel,
                flag=self.fuel_import_flag[fuel],
                data_id=self.data_id,
            ).build(db_conn)

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
            for emission, factors in self.input_emission_factors.items():
                if fuel in factors:
                    technology.with_input_emission_factor(
                        emission,
                        input_commodity,
                        factors[fuel].values,
                        **_metadata_kwargs(factors[fuel].metadata),
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

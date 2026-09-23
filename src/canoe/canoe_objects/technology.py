"""
A single Temoa technology and the parameter tables that describe it.

`TechnologyEntity` is the building block for anything that converts input
commodities into output commodities. Higher-level entities, such as
`FuelServingTechnologyEntity`, decide how many technologies to create and hand the
values to `TechnologyEntity` objects.

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py` (data sets `COMDOC*`, regions ON/QC, periods 2020-2035,
commodity labels `C_elc`, `C_ng`, `C_D_DOC`, `C_D_SPH`, `C_D_SPC`).
"""

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any

import numpy as np
from canoe_schema.v4_0 import (
    CapacityToActivity,
    CostFixed,
    CostInvest,
    Efficiency,
    ExistingCapacity,
    LifetimeTech,
    LimitAnnualCapacityFactor,
    LimitTechInputSplit,
    LimitTechInputSplitAnnual,
    OperatorCode,
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
    """
    Share of one input commodity in a technology's inputs, by region and period.

    Parameters
    ----------
    parameter : Parameter[RegionPeriodArray]
        Shares (0-1) and their metadata.
    operator : OperatorCode
        Whether the share is an upper bound (`le`), lower bound (`ge`) or exact (`e`).
    annual : bool
        Enforce the share over the year (`limit_tech_input_split_annual`) instead of
        in every time slice (`limit_tech_input_split`).
    """

    parameter: Parameter[RegionPeriodArray]
    operator: OperatorCode
    annual: bool


@dataclass(frozen=True)
class CapacityFactorLimit:
    """
    Limit on the annual capacity factor, by region and vintage.

    Parameters
    ----------
    parameter : Parameter[RegionVintageArray]
        Capacity factors (0-1) and their metadata.
    operator : OperatorCode
        Whether the factor is an upper bound (`le`), lower bound (`ge`) or exact (`e`).
    """

    parameter: Parameter[RegionVintageArray]
    operator: OperatorCode


class TechnologyEntity:
    """
    A single technology: one row in `technology`, with any number of input and output
    commodities (one efficiency per (input, output) pair, see `with_efficiency`).

    Configure it with the `set_*` and `with_*` methods (they return the entity, so
    calls can be chained) and write it with `build`. Every parameter is a labeled
    array; `build` writes one row per non-NaN cell, converting regions to their short
    code and filling notes, data source, data quality and `data_id` as described by
    `RowOptions`. Input and output commodities must already exist in the database.

    The `with_*` methods share these optional metadata arguments, stored as a
    `ParameterMetadata`: `notes`, `data_quality`, `reference_code` and, for tables
    with a units column, `units`.

    `validate` (called by `build`) catches inconsistencies Temoa would otherwise
    silently drop or turn into an infeasible model:

    - the technology has no inputs, or non-positive efficiencies
    - a parameter was set but has no values (all NaN)
    - input splits for commodities that are not inputs, or adding up to more than 1
    - existing capacity or investment costs for a (region, vintage) without any
      efficiency
    - fixed costs for periods before the vintage or after the end of its lifetime
    - capacity factor limits for commodities that are not outputs

    Parameters
    ----------
    name : str
        Technology name (`tech` column).
    output_commodity : str
        Main commodity produced by the technology: the output used by
        `with_efficiency` and `with_limit_annual_capacity_factor` unless they are
        given another one.
    data_id : DatasetIdentifier
        Data set the rows belong to.
    description : str, optional
        Description in the `technology` table.
    sector : CANOESector, optional
        Sector of the technology, also registered in `sector_label`.
    flag : TechnologyTypeCode
        Technology type, production (`p`) by default.
    include_region_in_data_id, notes_only_on_first, reference_only_on_first : bool
        How metadata is spread over rows, see `RowOptions`.

    Examples
    --------
    A natural gas furnace available in 2025 and 2030 in Ontario and Quebec:

    >>> from canoe.canoe_objects.array_types import RegionalValuesArray, RegionVintageArray
    >>> from canoe.common import CANOEProvince, CANOESector
    >>> from canoe.common.naming import DatasetIdentifier
    >>> regions = [CANOEProvince.ONTARIO, CANOEProvince.QUEBEC]
    >>> furnace = (
    ...     TechnologyEntity(
    ...         name="C_SPH_NG_FRN",
    ...         output_commodity="C_D_DOC",
    ...         data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ...         description="natural gas furnace",
    ...         sector=CANOESector.Commercial,
    ...     )
    ...     .set_annual()
    ...     .with_efficiency(
    ...         "C_ng",
    ...         RegionVintageArray(regions, [2025, 2030], fill=0.9),
    ...         notes="AEO typical gas furnace",
    ...     )
    ...     .with_lifetime(RegionalValuesArray(regions, fill=19.6))
    ... )
    >>> furnace.inputs
    ['C_ng']
    >>> furnace.build(db)
    >>> db.execute("SELECT tech, flag, sector, annual FROM technology").fetchall()
    [('C_SPH_NG_FRN', 'p', 'commercial', 1)]
    >>> for row in db.execute(
    ...     "SELECT region, input_comm, vintage, output_comm, efficiency, notes, data_id"
    ...     " FROM efficiency"
    ... ):
    ...     print(row)
    ('ON', 'C_ng', 2025, 'C_D_DOC', 0.9, 'AEO typical gas furnace', 'COMDOCON001')
    ('ON', 'C_ng', 2030, 'C_D_DOC', 0.9, None, 'COMDOCON001')
    ('QC', 'C_ng', 2025, 'C_D_DOC', 0.9, None, 'COMDOCQC001')
    ('QC', 'C_ng', 2030, 'C_D_DOC', 0.9, None, 'COMDOCQC001')

    Lifetimes are rounded to whole years:

    >>> db.execute("SELECT region, tech, lifetime, units FROM lifetime_tech").fetchall()
    [('ON', 'C_SPH_NG_FRN', 20.0, 'year'), ('QC', 'C_SPH_NG_FRN', 20.0, 'year')]
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
        # (input commodity, output commodity) -> efficiencies
        self.efficiencies: dict[tuple[str, str], Parameter[RegionVintageArray]] = {}
        # input commodity -> input split
        self.input_splits: dict[str, InputSplit] = {}
        self.lifetime: Parameter[RegionalValuesArray] | None = None
        self.capacity_to_activity: Parameter[RegionalValuesArray] | None = None
        self.existing_capacity: Parameter[RegionVintageArray] | None = None
        self.investment_cost: Parameter[RegionVintageArray] | None = None
        self.fixed_cost: Parameter[RegionVintagePeriodArray] | None = None
        # output commodity -> capacity factor limit
        self.capacity_factor_limits: dict[str, CapacityFactorLimit] = {}

    @property
    def inputs(self) -> list[str]:
        """Input commodities, in the order they were added with `with_efficiency`"""
        return list(dict.fromkeys(i for i, _ in self.efficiencies))

    @property
    def outputs(self) -> list[str]:
        """Output commodities, in the order they were added with `with_efficiency`"""
        return list(dict.fromkeys(o for _, o in self.efficiencies))

    def set_annual(self, annual: bool = True):
        """
        Mark the technology as annual (`annual` column): its activity is decided per
        year instead of per time slice, following the demand profile.
        """
        self.annual = int(annual)
        return self

    def set_unlimited_capacity(self, unlimited: bool = True):
        """
        Mark the technology as having unlimited capacity (`unlim_cap` column): Temoa
        does not track its capacity, only its activity.
        """
        self.unlimited_capacity = int(unlimited)
        return self

    def with_efficiency(
        self,
        input_commodity: str,
        efficiencies: RegionVintageArray,
        output_commodity: str | None = None,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """
        Add a conversion from `input_commodity` to `output_commodity`, making them an
        input and an output of the technology.

        Writes `efficiency`: one row per (region, vintage) with a value. The vintages
        with a value are the ones the technology can be built in (or, for existing
        capacity, was built in). Calling it again with the same input and output
        replaces their efficiencies.

        Parameters
        ----------
        input_commodity : str
            Name of the input commodity.
        efficiencies : RegionVintageArray
            Output per unit of input, by region and vintage. Must be positive.
        output_commodity : str, optional
            Name of the output commodity, the entity's `output_commodity` by default.

        Examples
        --------
        A technology can have several inputs, e.g. a dual-fuel heater:

        >>> from canoe.common import CANOESector
        >>> data_id = DatasetIdentifier(CANOESector.Commercial, "DOC", "001")
        >>> regions = [CANOEProvince.ONTARIO]
        >>> heater = (
        ...     TechnologyEntity("C_DUAL", "C_D_DOC", data_id)
        ...     .with_efficiency("C_elc", RegionVintageArray(regions, [2025], fill=1.0))
        ...     .with_efficiency("C_ng", RegionVintageArray(regions, [2025], fill=0.8))
        ... )
        >>> heater.inputs
        ['C_elc', 'C_ng']

        Or several outputs, e.g. a heat pump serving heating and cooling:

        >>> heat_pump = (
        ...     TechnologyEntity("C_SPHC_HP", "C_D_SPH", data_id)
        ...     .with_efficiency("C_elc", RegionVintageArray(regions, [2025], fill=3.4))
        ...     .with_efficiency(
        ...         "C_elc",
        ...         RegionVintageArray(regions, [2025], fill=4.1),
        ...         output_commodity="C_D_SPC",
        ...     )
        ... )
        >>> heat_pump.inputs, heat_pump.outputs
        (['C_elc'], ['C_D_SPH', 'C_D_SPC'])
        >>> heat_pump.build(db)
        >>> db.execute("SELECT input_comm, output_comm, efficiency FROM efficiency").fetchall()
        [('C_elc', 'C_D_SPH', 3.4), ('C_elc', 'C_D_SPC', 4.1)]
        """
        output = output_commodity or self.output_commodity
        self.efficiencies[(input_commodity, output)] = Parameter(
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

        Writes `limit_tech_input_split_annual` (or `limit_tech_input_split` if not
        `annual`): one row per (region, period) with a value. `input_commodity` must
        be an input (see `with_efficiency`), and the shares of all inputs must add up
        to at most 1 in every region and period.

        Parameters
        ----------
        input_commodity : str
            Name of the input commodity.
        splits : RegionPeriodArray
            Share (0-1) of the input, by region and period.
        operator : OperatorCode
            Upper bound (`le`, default), lower bound (`ge`) or exact share (`e`).
        annual : bool
            Enforce the share over the year instead of in every time slice.

        Examples
        --------
        Fix the fuel mix of a dual-fuel technology to 70% electricity, 30% gas:

        >>> from canoe.common import CANOESector
        >>> regions = [CANOEProvince.ONTARIO]
        >>> periods = [2025, 2030]
        >>> dual = (
        ...     TechnologyEntity(
        ...         "C_DUAL", "C_D_DOC", DatasetIdentifier(CANOESector.Commercial, "DOC", "001")
        ...     )
        ...     .with_efficiency("C_elc", RegionVintageArray(regions, [2025], fill=1.0))
        ...     .with_efficiency("C_ng", RegionVintageArray(regions, [2025], fill=1.0))
        ...     .with_input_split("C_elc", RegionPeriodArray(regions, periods, fill=0.7))
        ...     .with_input_split("C_ng", RegionPeriodArray(regions, periods, fill=0.3))
        ... )
        >>> dual.build(db)
        >>> for row in db.execute(
        ...     "SELECT region, period, input_comm, operator, proportion"
        ...     " FROM limit_tech_input_split_annual"
        ... ):
        ...     print(row)
        ('ON', 2025, 'C_elc', 'le', 0.7)
        ('ON', 2030, 'C_elc', 'le', 0.7)
        ('ON', 2025, 'C_ng', 'le', 0.3)
        ('ON', 2030, 'C_ng', 'le', 0.3)
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
        """
        Set the technical lifetime.

        Writes `lifetime_tech`: one row per region with a value, rounded to whole
        years. Without it, Temoa uses its default lifetime.

        Parameters
        ----------
        lifetimes : RegionalValuesArray
            Lifetime in years, by region.
        units : str, optional
            Defaults to "year".
        """
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
        """
        Set the capacity-to-activity ratio: the activity one unit of capacity
        produces when fully used for a year (e.g. 1 for capacity in PJ/y and
        activity in PJ).

        Writes `capacity_to_activity`: one row per region with a value.

        Parameters
        ----------
        capacity_to_activity : RegionalValuesArray
            Ratio by region.
        """
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
        """
        Set the capacity installed before the first model period.

        Writes `existing_capacity`: one row per (region, vintage) with a value.
        Every (region, vintage) with capacity needs an efficiency for at least one
        input (checked by `validate`).

        Parameters
        ----------
        existing_capacity : RegionVintageArray
            Installed capacity by region and (existing) vintage.
        """
        self.existing_capacity = Parameter(
            existing_capacity,
            ParameterMetadata(notes, reference_code, data_quality, units),
        )
        return self

    def with_investment_cost(
        self,
        investment_cost: RegionVintageArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """
        Set the cost of building one unit of new capacity.

        Writes `cost_invest`: one row per (region, vintage) with a value. Every
        (region, vintage) with a cost needs an efficiency for at least one input
        (checked by `validate`).

        Parameters
        ----------
        investment_cost : RegionVintageArray
            Cost by region and (new) vintage.

        Examples
        --------
        >>> from canoe.common import CANOESector
        >>> regions = [CANOEProvince.ONTARIO]
        >>> boiler = (
        ...     TechnologyEntity(
        ...         "C_ELC_BLR", "C_D_DOC", DatasetIdentifier(CANOESector.Commercial, "DOC", "001")
        ...     )
        ...     .with_efficiency("C_elc", RegionVintageArray(regions, [2025, 2030], fill=0.98))
        ...     .with_investment_cost(
        ...         RegionVintageArray(regions, [2025, 2030], fill=2.4), units="M$/PJ/y"
        ...     )
        ... )
        >>> boiler.build(db)
        >>> db.execute("SELECT region, tech, vintage, cost, units FROM cost_invest").fetchall()
        [('ON', 'C_ELC_BLR', 2025, 2.4, 'M$/PJ/y'), ('ON', 'C_ELC_BLR', 2030, 2.4, 'M$/PJ/y')]
        """
        self.investment_cost = Parameter(
            investment_cost,
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
        """
        Set the fixed operation and maintenance cost per unit of capacity.

        Writes `cost_fixed`: one row per (region, vintage, period) with a value. Only
        periods in which the vintage is alive are allowed: not before the vintage,
        and (if a lifetime is set) before `vintage + lifetime` (checked by `validate`).

        Parameters
        ----------
        fixed_cost : RegionVintagePeriodArray
            Cost by region, vintage and period.
        """
        self.fixed_cost = Parameter(
            fixed_cost, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_limit_annual_capacity_factor(
        self,
        capacity_factors: RegionVintageArray,
        operator: OperatorCode = OperatorCode.LE,
        output_commodity: str | None = None,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        """
        Limit the annual capacity factor of one output: the fraction of the year's
        full-capacity output the technology can deliver.

        Writes `limit_annual_capacity_factor`: one row per (region, vintage) with a
        value. Calling it again with the same output replaces its limit.

        Parameters
        ----------
        capacity_factors : RegionVintageArray
            Capacity factor (0-1) by region and vintage.
        operator : OperatorCode
            Upper bound (`le`, default), lower bound (`ge`) or exact factor (`e`).
        output_commodity : str, optional
            Output the limit applies to, the entity's `output_commodity` by default.
            Must be an output (see `with_efficiency`).
        """
        output = output_commodity or self.output_commodity
        self.capacity_factor_limits[output] = CapacityFactorLimit(
            Parameter(
                capacity_factors,
                ParameterMetadata(notes, reference_code, data_quality),
            ),
            operator,
        )
        return self

    def validate(self) -> None:
        """
        Check the parameters are consistent before writing them (called by `build`).

        Raises
        ------
        ValueError
            On the first inconsistency found; see the class docstring for the list.

        Examples
        --------
        >>> from canoe.common import CANOESector
        >>> data_id = DatasetIdentifier(CANOESector.Commercial, "DOC", "001")
        >>> TechnologyEntity("C_EMPTY", "C_D_DOC", data_id).validate()
        Traceback (most recent call last):
        ...
        ValueError: Technology C_EMPTY has no inputs (no efficiencies)

        Existing capacity needs an efficiency for its vintage:

        >>> regions = [CANOEProvince.ONTARIO]
        >>> (
        ...     TechnologyEntity("C_OLD", "C_D_DOC", data_id)
        ...     .with_efficiency("C_elc", RegionVintageArray(regions, [2025], fill=1.0))
        ...     .with_existing_capacity(RegionVintageArray(regions, [2020], fill=5.0))
        ...     .validate()
        ... )
        Traceback (most recent call last):
        ...
        ValueError: Technology C_OLD: existing capacity without efficiency at Ontario, 2020
        """
        if not self.efficiencies:
            raise ValueError(f"Technology {self.name} has no inputs (no efficiencies)")

        # Parameters that were set but have no values (all NaN)
        parameters: dict[str, Parameter[Any] | None] = {
            **{
                f"efficiency ({i} -> {o})": p for (i, o), p in self.efficiencies.items()
            },
            **{f"input split ({i})": s.parameter for i, s in self.input_splits.items()},
            "lifetime": self.lifetime,
            "capacity to activity": self.capacity_to_activity,
            "existing capacity": self.existing_capacity,
            "investment cost": self.investment_cost,
            "fixed cost": self.fixed_cost,
            **{
                f"annual capacity factor limit ({o})": limit.parameter
                for o, limit in self.capacity_factor_limits.items()
            },
        }
        for parameter_name, parameter in parameters.items():
            if parameter is not None and not parameter.values.to_records():
                raise ValueError(
                    f"Technology {self.name}: {parameter_name} was set but has no values"
                )

        # (region, vintage) cells with at least one efficiency
        efficiency_cells: set[tuple[CANOEProvince, int]] = set()
        for (
            input_commodity,
            output_commodity,
        ), efficiency in self.efficiencies.items():
            for record in efficiency.values.to_records():
                if record["value"] <= 0:
                    raise ValueError(
                        f"Technology {self.name}: non-positive efficiency {record['value']} "
                        + f"for {input_commodity} -> {output_commodity} "
                        + f"at {record['region']}, {record['vintage']}"
                    )
                efficiency_cells.add((record["region"], record["vintage"]))

        # Capacity factor limits
        not_outputs = set(self.capacity_factor_limits) - set(self.outputs)
        if not_outputs:
            raise ValueError(
                f"Technology {self.name}: capacity factor limits for commodities that are not outputs: {not_outputs}"
            )

        # Input splits
        not_inputs = set(self.input_splits) - set(self.inputs)
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

        # Existing capacity and investment costs
        vintage_parameters = {
            "existing capacity": self.existing_capacity,
            "investment cost": self.investment_cost,
        }
        for parameter_name, parameter in vintage_parameters.items():
            if parameter is None:
                continue
            for record in parameter.values.to_records():
                if (record["region"], record["vintage"]) not in efficiency_cells:
                    raise ValueError(
                        f"Technology {self.name}: {parameter_name} without efficiency "
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
        """
        Validate the technology and write it to the database.

        Writes the `technology` row (and its `technology_label`, plus `sector_label`
        if a sector is set), then one set of rows per parameter that was set. Rows
        that already exist are left untouched (insert or ignore).

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.

        Raises
        ------
        ValueError
            If `validate` fails. Nothing is written in that case.
        """
        self.validate()
        options = self.row_options

        # Sector label
        if self.sector is not None:
            write_label(db_conn, self.sector)

        # Technology table
        technology = Technology(
            tech=self.name,
            flag=self.flag,
            # Same value `write_label` registers in sector_label
            sector=self.sector.name.lower() if self.sector is not None else None,
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

        # Efficiencies (one set of rows per input and output)
        for (
            input_commodity,
            output_commodity,
        ), efficiency in self.efficiencies.items():
            meta = efficiency.metadata
            efficiencies = [
                Efficiency(
                    region=row["region"].short(),
                    input_comm=input_commodity,
                    tech=self.name,
                    vintage=row["vintage"],
                    output_comm=output_commodity,
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

        # Investment costs
        if self.investment_cost:
            meta = self.investment_cost.metadata
            investment_costs = [
                CostInvest(
                    region=row["region"].short(),
                    tech=self.name,
                    vintage=row["vintage"],
                    cost=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=options.dataset_code(row["region"]),
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.investment_cost.values.to_records())
            ]
            sql, params = CostInvest.bulk_insert_or_ignore_sql(
                investment_costs, include_nulls=True
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

        # Annual capacity factor limits (one set of rows per output)
        for output_commodity, limit in self.capacity_factor_limits.items():
            meta = limit.parameter.metadata
            capacity_factors = [
                LimitAnnualCapacityFactor(
                    region=row["region"].short(),
                    tech_or_group=self.name,
                    vintage=row["vintage"],
                    output_comm=output_commodity,
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

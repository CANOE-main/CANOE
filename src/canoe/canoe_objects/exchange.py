"""
A Temoa exchange technology: one technology carrying a commodity between regions.

Temoa indexes the parameters of an exchange technology by a region pair written
`<from>-<to>` (e.g. `AB-BC`): each direction is a process of its own, with its own
efficiency and capacity factors, but both directions share one capacity (Temoa's
`RegionalExchangeCapacity` constraint), so they must have the same existing capacity.

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py` (data sets `COMDOC*`, regions ON/QC, periods 2020-2035,
time slices D001 x H01/H02, commodity label `C_elc`).
"""

from sqlite3 import Connection
from typing import Any

import numpy as np
from canoe_schema.v4_0 import (
    CapacityFactorTech,
    CapacityToActivity,
    CostVariable,
    Efficiency,
    ExistingCapacity,
    LifetimeTech,
    Technology,
    TechnologyTypeCode,
)

from canoe.canoe_objects.array_types import (
    PairPeriodArray,
    PairSeasonTodArray,
    PairValuesArray,
    RegionPair,
)
from canoe.canoe_objects.parameter import Parameter, ParameterMetadata, RowOptions
from canoe.common import CANOESector, DataQualityProfile
from canoe.common.db_tools import write_label
from canoe.common.naming import DatasetIdentifier


def pair_region(pair: RegionPair) -> str:
    """
    Region of a direction in Temoa's tables.

    Examples
    --------
    >>> from canoe.common import CANOEProvince
    >>> pair_region((CANOEProvince.ALBERTA, CANOEProvince.BRITISH_COLUMBIA))
    'AB-BC'
    """
    return f"{pair[0].short()}-{pair[1].short()}"


class ExchangeTechnologyEntity:
    """
    An exchange technology (`exchange` flag) carrying `commodity` between regions, in
    the directions with an efficiency, all of a single vintage.

    Configure it with the `with_*` methods (they return the entity) and write it with
    `build`. Values are labeled arrays by direction (`RegionPair`); `build` writes one
    row per non-NaN cell, with the region `<from>-<to>` and the module-wide data set
    (a direction has no single province). Metadata arguments as in
    `TechnologyEntity`.

    `validate` (called by `build`) checks that:

    - the technology has efficiencies, within (0, 1]
    - every direction has its reverse, with the same existing capacity
    - the other parameters are only for directions with an efficiency, and variable
      costs not before the vintage
    - capacity factors are within [0, 1]

    Parameters
    ----------
    name : str
        Technology name.
    commodity : str
        Commodity carried (input and output).
    vintage : int
        The single vintage of every direction.
    data_id : DatasetIdentifier
        Data set the rows belong to.
    description : str, optional
        Description in the `technology` table.
    sector : CANOESector, optional
        Sector of the technology.

    Examples
    --------
    >>> from canoe.common import CANOEProvince, CANOESector
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> pairs = [(ON, QC), (QC, ON)]
    >>> intertie = (
    ...     ExchangeTechnologyEntity(
    ...         "C_INT", "C_elc", 2020, DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ...     )
    ...     .with_efficiency(PairValuesArray(pairs, fill=0.97))
    ...     .with_existing_capacity(PairValuesArray(pairs, fill=2.5), units="GW")
    ... )
    >>> intertie.build(db)
    >>> db.execute("SELECT tech, exchange FROM technology").fetchall()
    [('C_INT', 1)]
    >>> db.execute(
    ...     "SELECT region, input_comm, vintage, output_comm, efficiency, data_id"
    ...     " FROM efficiency"
    ... ).fetchall()
    [('ON-QC', 'C_elc', 2020, 'C_elc', 0.97, 'COMDOC001'), ('QC-ON', 'C_elc', 2020, 'C_elc', 0.97, 'COMDOC001')]
    """

    def __init__(
        self,
        name: str,
        commodity: str,
        vintage: int,
        data_id: DatasetIdentifier,
        description: str | None = None,
        sector: CANOESector | None = None,
    ) -> None:
        self.name: str = name
        self.commodity: str = commodity
        self.vintage: int = vintage
        self.description: str | None = description
        self.sector: CANOESector | None = sector
        self.row_options: RowOptions = RowOptions(
            data_id=data_id, include_region_in_data_id=False
        )

        self.efficiency: Parameter[PairValuesArray] | None = None
        self.existing_capacity: Parameter[PairValuesArray] | None = None
        self.lifetime: Parameter[PairValuesArray] | None = None
        self.capacity_to_activity: Parameter[PairValuesArray] | None = None
        self.variable_cost: Parameter[PairPeriodArray] | None = None
        # Time-sliced (hourly), written as plain tuples, see `build`
        self.capacity_factors: Parameter[PairSeasonTodArray] | None = None

    def with_efficiency(
        self,
        efficiencies: PairValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """Set the share of the commodity sent that arrives, by direction
        (`efficiency`)."""
        self.efficiency = Parameter(
            efficiencies, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_existing_capacity(
        self,
        capacities: PairValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """Set the capacity of the vintage, the same in both directions of a pair
        (`existing_capacity`)."""
        self.existing_capacity = Parameter(
            capacities, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_lifetime(
        self,
        lifetimes: PairValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = "year",
    ):
        """Set the lifetime in years, by direction (`lifetime_tech`, rounded)."""
        self.lifetime = Parameter(
            lifetimes, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_capacity_to_activity(
        self,
        factors: PairValuesArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """Set the activity of a unit of capacity over a year, by direction
        (`capacity_to_activity`)."""
        self.capacity_to_activity = Parameter(
            factors, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_variable_cost(
        self,
        costs: PairPeriodArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
        units: str | None = None,
    ):
        """Set the cost per unit carried, by direction and period
        (`cost_variable`)."""
        self.variable_cost = Parameter(
            costs, ParameterMetadata(notes, reference_code, data_quality, units)
        )
        return self

    def with_capacity_factor(
        self,
        capacity_factors: PairSeasonTodArray,
        notes: str | None = None,
        data_quality: DataQualityProfile | None = None,
        reference_code: str | None = None,
    ):
        """
        Set the share of the capacity available in each time slice, by direction
        (`capacity_factor_tech`), e.g. a lower transfer capability in summer.

        Examples
        --------
        >>> from canoe.common import CANOEProvince, CANOESector
        >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
        >>> pairs = [(ON, QC), (QC, ON)]
        >>> factors = PairSeasonTodArray(pairs, ["D001"], ["H01", "H02"], fill=1.0)
        >>> factors.set(0.5, pair=(QC, ON), tod="H02")
        >>> (
        ...     ExchangeTechnologyEntity(
        ...         "C_INT", "C_elc", 2020, DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
        ...     )
        ...     .with_efficiency(PairValuesArray(pairs, fill=1.0))
        ...     .with_capacity_factor(factors)
        ...     .build(db)
        ... )
        >>> db.execute(
        ...     "SELECT region, season, tod, factor FROM capacity_factor_tech"
        ... ).fetchall()
        [('ON-QC', 'D001', 'H01', 1.0), ('ON-QC', 'D001', 'H02', 1.0), ('QC-ON', 'D001', 'H01', 1.0), ('QC-ON', 'D001', 'H02', 0.5)]
        """
        self.capacity_factors = Parameter(
            capacity_factors, ParameterMetadata(notes, reference_code, data_quality)
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
        >>> from canoe.common import CANOEProvince, CANOESector
        >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
        >>> (
        ...     ExchangeTechnologyEntity(
        ...         "C_INT", "C_elc", 2020, DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
        ...     )
        ...     .with_efficiency(PairValuesArray([(ON, QC)], fill=1.0))
        ...     .validate()
        ... )
        Traceback (most recent call last):
        ...
        ValueError: Exchange C_INT: ON-QC without its reverse, QC-ON
        """
        if self.efficiency is None or not self.efficiency.values.to_records():
            raise ValueError(f"Exchange {self.name} has no efficiencies")
        efficiencies: dict[RegionPair, float] = {
            r["pair"]: r["value"] for r in self.efficiency.values.to_records()
        }
        for pair, value in efficiencies.items():
            if not 0 < value <= 1:
                raise ValueError(
                    f"Exchange {self.name}: efficiency {value} outside (0, 1] at "
                    + pair_region(pair)
                )
            if (pair[1], pair[0]) not in efficiencies:
                raise ValueError(
                    f"Exchange {self.name}: {pair_region(pair)} without its reverse, "
                    + pair_region((pair[1], pair[0]))
                )

        by_pair: dict[str, Parameter[Any] | None] = {
            "existing capacity": self.existing_capacity,
            "lifetime": self.lifetime,
            "capacity to activity": self.capacity_to_activity,
            "variable cost": self.variable_cost,
        }
        for parameter_name, parameter in by_pair.items():
            if parameter is None:
                continue
            records = parameter.values.to_records()
            if not records:
                raise ValueError(
                    f"Exchange {self.name}: {parameter_name} was set but has no values"
                )
            for record in records:
                if record["pair"] not in efficiencies:
                    raise ValueError(
                        f"Exchange {self.name}: {parameter_name} without efficiency "
                        + f"at {pair_region(record['pair'])}"
                    )
                if record.get("period", self.vintage) < self.vintage:
                    raise ValueError(
                        f"Exchange {self.name}: {parameter_name} for period "
                        + f"{record['period']} before vintage {self.vintage}"
                    )

        if self.existing_capacity:
            capacities: dict[RegionPair, float] = {
                r["pair"]: r["value"]
                for r in self.existing_capacity.values.to_records()
            }
            for pair, capacity in capacities.items():
                reverse = capacities.get((pair[1], pair[0]))
                if reverse is None or not np.isclose(capacity, reverse):
                    raise ValueError(
                        f"Exchange {self.name}: existing capacity {capacity} at "
                        + f"{pair_region(pair)}, {reverse} in reverse (must be equal)"
                    )

        if self.capacity_factors:
            values = self.capacity_factors.values
            data = values.data
            if np.isnan(data).all():
                raise ValueError(
                    f"Exchange {self.name}: capacity factor was set but has no values"
                )
            if np.nanmin(data) < 0 or np.nanmax(data) > 1:
                raise ValueError(
                    f"Exchange {self.name}: capacity factor outside [0, 1] "
                    + f"({np.nanmin(data)} to {np.nanmax(data)})"
                )
            has_value = ~np.isnan(data).all(axis=(1, 2))
            for i in np.nonzero(has_value)[0]:
                pair = values.coords["pair"][i]
                if pair not in efficiencies:
                    raise ValueError(
                        f"Exchange {self.name}: capacity factor without efficiency "
                        + f"at {pair_region(pair)}"
                    )

    def build(self, db_conn: Connection):
        """
        Validate the technology and write it to the database: the `technology` row
        (with its labels), then one set of rows per parameter that was set. Rows that
        already exist are left untouched (insert or ignore).

        Raises
        ------
        ValueError
            If `validate` fails. Nothing is written in that case.
        """
        self.validate()
        assert self.efficiency is not None
        options = self.row_options
        data_id = options.dataset_code()

        if self.sector is not None:
            write_label(db_conn, self.sector)
        technology = Technology(
            tech=self.name,
            flag=TechnologyTypeCode.P,
            sector=self.sector.name.lower() if self.sector is not None else None,
            description=self.description,
            exchange=1,
            data_id=data_id,
        )
        sql, params = Technology.to_insert_or_ignore_sql(technology)
        write_label(db_conn, technology)
        db_conn.execute(sql, params)

        # Efficiencies
        meta = self.efficiency.metadata
        efficiencies = [
            Efficiency(
                region=pair_region(row["pair"]),
                input_comm=self.commodity,
                tech=self.name,
                vintage=self.vintage,
                output_comm=self.commodity,
                efficiency=row["value"],
                units=meta.units,
                notes=options.notes(meta, i),
                data_source=options.reference(meta, i),
                data_id=data_id,
                **options.data_quality(meta, i),
            )
            for i, row in enumerate(self.efficiency.values.to_records())
        ]
        sql, params = Efficiency.bulk_insert_or_ignore_sql(
            efficiencies, include_nulls=True
        )
        db_conn.executemany(sql, params)

        # Existing capacities
        if self.existing_capacity:
            meta = self.existing_capacity.metadata
            capacities = [
                ExistingCapacity(
                    region=pair_region(row["pair"]),
                    tech=self.name,
                    vintage=self.vintage,
                    capacity=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=data_id,
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.existing_capacity.values.to_records())
            ]
            sql, params = ExistingCapacity.bulk_insert_or_ignore_sql(
                capacities, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Lifetimes
        if self.lifetime:
            meta = self.lifetime.metadata
            lifetimes = [
                LifetimeTech(
                    region=pair_region(row["pair"]),
                    tech=self.name,
                    lifetime=np.round(row["value"]),
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=data_id,
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
            factors = [
                CapacityToActivity(
                    region=pair_region(row["pair"]),
                    tech=self.name,
                    c2a=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=data_id,
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.capacity_to_activity.values.to_records())
            ]
            sql, params = CapacityToActivity.bulk_insert_or_ignore_sql(
                factors, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Variable costs
        if self.variable_cost:
            meta = self.variable_cost.metadata
            costs = [
                CostVariable(
                    region=pair_region(row["pair"]),
                    period=row["period"],
                    tech=self.name,
                    vintage=self.vintage,
                    cost=row["value"],
                    units=meta.units,
                    notes=options.notes(meta, i),
                    data_source=options.reference(meta, i),
                    data_id=data_id,
                    **options.data_quality(meta, i),
                )
                for i, row in enumerate(self.variable_cost.values.to_records())
            ]
            sql, params = CostVariable.bulk_insert_or_ignore_sql(
                costs, include_nulls=True
            )
            db_conn.executemany(sql, params)

        # Capacity factors: hourly, plain tuples (columns spelled out), values
        # checked on the array by `validate`
        if self.capacity_factors:
            meta = self.capacity_factors.metadata
            quality = options.data_quality(meta, 0)
            quality_columns = ("dq_cred", "dq_geog", "dq_struc", "dq_tech", "dq_time")
            sql = (
                f"INSERT OR IGNORE INTO {CapacityFactorTech.__table_name__} "
                + "(region, season, tod, tech, factor, notes, data_source, "
                + "dq_cred, dq_geog, dq_struc, dq_tech, dq_time, data_id) "
                + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            db_conn.executemany(
                sql,
                (
                    (
                        pair_region(row["pair"]),  # region
                        row["season"],  # season
                        row["tod"],  # tod
                        self.name,  # tech
                        float(row["value"]),  # factor
                        options.notes(meta, i),  # notes
                        options.reference(meta, i),  # data_source
                        *(quality.get(c) if i == 0 else None for c in quality_columns),
                        data_id,  # data_id
                    )
                    for i, row in enumerate(self.capacity_factors.values.to_records())
                ),
            )

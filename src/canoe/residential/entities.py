"""
Temoa objects of the residential sector.

Takes the parameters computed in `build.py` (tidy frames, see each function) and
turns them into `canoe_objects` entities. Nothing in here touches the database; the
caller decides when to `.build()` the returned entities (the demands first, as the
technologies output them).

Built in stages: the demands, the existing and the new technologies (here), then
lighting and other appliances.
"""

from dataclasses import dataclass
from sqlite3 import Connection

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode
from loguru import logger

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import FuelCommodityEntity, SourceCommodityEntity
from canoe.canoe_objects.demand import (
    DemandEntity,
    DemandSeriesArray,
    DemandSpecificDistributionArray,
)
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_commodity_name,
)
from canoe.common.time_slices import TimeSlice

from .end_uses import ResidentialEndUse
from .technology_catalog import ExistingTechnology, NewTechnology


def end_use_demand_name(end_use: ResidentialEndUse) -> str:
    """
    Name of the demand commodity of an end use.

    Examples
    --------
    >>> end_use_demand_name(ResidentialEndUse.CookingRanges)
    'R_D_APP_COOK_RNG'
    """
    return get_commodity_name(
        CANOESector.Residential, end_use.short_desc(), is_demand=True
    )


def fuel_commodity_flag(fuel: CANOEFuel) -> CommodityTypeCode:
    """
    Type of the residential commodity of `fuel`: physical (`p`) for electricity,
    annual (`a`) for the other fuels.

    Examples
    --------
    >>> fuel_commodity_flag(CANOEFuel.Electricity), fuel_commodity_flag(CANOEFuel.Wood)
    (<CommodityTypeCode.P: 'p'>, <CommodityTypeCode.A: 'a'>)
    """
    if fuel == CANOEFuel.Electricity:
        return CommodityTypeCode.P
    return CommodityTypeCode.A


def source_commodity_name() -> str:
    """
    Name of the free source commodity the solar water heater takes.

    Examples
    --------
    >>> source_commodity_name()
    'R_ethos'
    """
    return f"{CANOESector.Residential.get_tag()}_ethos"


def build_end_use_demand(
    end_use: ResidentialEndUse,
    demand: pd.DataFrame,
    dsd: pd.DataFrame | None,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    time_slices: list[TimeSlice],
    demand_notes: str,
    dsd_notes: str,
    data_id: DatasetIdentifier,
) -> DemandEntity:
    """
    The demand of `end_use`, in its units (see `ResidentialEndUse.demand_units`),
    and its demand-specific distribution.

    Demand rows are written where the demand is positive. The distribution is the
    same in every model period; every value given is written, zeros included (hours
    below `dsd_tolerance`).

    params:
    - demand: one row per (region, period, end use) with columns `region`
      (`CANOEProvince`), `period`, `end_use` (`ResidentialEndUse`) and `demand`; only
      the rows of `end_use` are read. Not modified.
    - dsd: one row per (region, end use, time slice) with columns `region`,
      `end_use`, `season`, `tod` and `dsd` (fractions adding up to 1 over the time
      slices of each region); only the rows of `end_use` are read. None for no
      distribution. Not modified.
    - time_slices: time slices of the distribution
    - demand_notes, dsd_notes: notes of the demand and distribution rows
    """
    # NOTE: enum columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== ResidentialEndUse.X` compares against str(ResidentialEndUse.X) (the name)
    # and never matches.
    rows = demand.loc[demand["end_use"].isin([end_use]) & (demand["demand"] > 0)]
    entity = DemandEntity(
        name=end_use_demand_name(end_use),
        commodity_description=f"demand for residential {end_use.get_desc_name()}",
        unit=end_use.demand_units(),
        data_id=data_id,
    ).with_demand_series(
        DemandSeriesArray(region=provinces, period=model_periods).fill_from_df(
            rows, dims=["region", "period"], value_col="demand"
        ),
        notes=demand_notes,
        data_quality=DataQualityProfile(cred=1, geog=1, struc=2, tech=1, time=3),
    )
    if dsd is None:
        return entity

    distribution = DemandSpecificDistributionArray(
        region=provinces,
        period=model_periods,
        season=sorted({t.season for t in time_slices}),
        tod=sorted({t.tod for t in time_slices}),
    ).fill_from_df(
        dsd.loc[dsd["end_use"].isin([end_use])],
        dims=["region", "season", "tod"],
        value_col="dsd",
    )  # Without a period, the values are broadcast to every period
    return entity.with_dsd(
        distribution,
        notes=dsd_notes,
        data_quality=DataQualityProfile(cred=1, geog=3, struc=2, tech=1, time=3),
    )


@dataclass(frozen=True)
class ExistingTechnologyParameters:
    """
    Parameters of existing technologies (any number of them), one long frame per
    parameter with a `technology` column (`ExistingTechnology`), and the notes of
    each parameter's rows. Every frame has a `region` column (`CANOEProvince`);
    vintages are existing vintages.

    Parameters
    ----------
    efficiency : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `fuel` (`CANOEFuel`) and
        `efficiency`: output (in the demand units of the end use) per PJ of the fuel.
    existing_capacity : pd.DataFrame
        Columns `region`, `technology`, `vintage` and `capacity`, in the capacity
        units of the end use (see `ResidentialEndUse.capacity_units`).
    capacity_factor : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `operator` (`OperatorCode`, e.g.
        a `ge` and a `le` row for a band) and `factor` (0-1).
    lifetime : pd.DataFrame
        Columns `region`, `technology` and `lifetime` (years).
    fixed_cost : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `period` and `cost` (M$ per unit of
        capacity and year); periods while the vintage is alive. A technology without
        rows has no fixed cost.
    efficiency_notes, existing_capacity_notes, capacity_factor_notes, lifetime_notes,
    fixed_cost_notes : str
        Notes of the rows of each parameter.
    """

    efficiency: pd.DataFrame
    existing_capacity: pd.DataFrame
    capacity_factor: pd.DataFrame
    lifetime: pd.DataFrame
    fixed_cost: pd.DataFrame
    efficiency_notes: str
    existing_capacity_notes: str
    capacity_factor_notes: str
    lifetime_notes: str
    fixed_cost_notes: str


def build_existing_technology(
    technology: ExistingTechnology,
    parameters: ExistingTechnologyParameters,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> FuelServingTechnologyEntity | None:
    """
    The existing technology `technology`: annual, with limited capacity, a capacity
    to activity of 1 (a unit of capacity running all year serves a unit of demand)
    and one input per fuel of its specification. Dual heating systems take both
    fuels with no input split: the model chooses the mix.

    The technology is written in the regions where it has existing capacity (rows of
    `parameters` in other regions are ignored); None if it has none anywhere.

    params:
    - parameters: see `ExistingTechnologyParameters`; only the rows of `technology`
      are read. Not modified.
    - model_periods: periods of the fixed costs

    Raises
    ------
    ValueError
        For other appliances (`ExistingTechnology.OtherAppliances`): they have no
        stock, but unlimited capacity.
    """
    if technology == ExistingTechnology.OtherAppliances:
        raise ValueError(
            f"{technology.value} has unlimited capacity, not existing capacity"
        )
    spec = technology.spec()
    end_use = spec.end_use

    # NOTE: enum columns are filtered with `isin` (see `build_end_use_demand`)
    def rows_of(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[frame["technology"].isin([technology])]

    capacity = rows_of(parameters.existing_capacity)
    capacity = capacity.loc[capacity["capacity"] > 0]
    if capacity.empty:
        return None
    regions = [p for p in provinces if p in set(capacity["region"])]
    vintages = sorted(set(capacity["vintage"]))

    def in_regions(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[frame["region"].isin(regions)]

    efficiency = in_regions(rows_of(parameters.efficiency))
    capacity_factor = in_regions(rows_of(parameters.capacity_factor))
    lifetime = in_regions(rows_of(parameters.lifetime))
    fixed_cost = in_regions(rows_of(parameters.fixed_cost))

    # The shared technology is named `R_<short_desc>-EXS`: the name of the catalog
    # without the sector tag and the scope
    tag = CANOESector.Residential.get_tag()
    scope = TechnologyCapacityScope.Existing.value
    entity = (
        FuelServingTechnologyEntity(
            sector=CANOESector.Residential,
            short_desc=technology.value.removeprefix(f"{tag}_").removesuffix(
                f"-{scope}"
            ),
            fuels=list(spec.fuels),
            fuel_import_flag={
                f: CommodityTypeCode.P
                if f == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for f in spec.fuels
            },
            output_commodity_name=end_use_demand_name(end_use),
            data_id=data_id,
            capacity_scope=TechnologyCapacityScope.Existing,
            description=f"{end_use.get_desc_name()} - {spec.description} - existing",
            grouping=FuelGrouping.Shared,
        )
        .set_annual()
        .with_efficiencies(
            {
                fuel: RegionVintageArray(regions, vintages).fill_from_df(
                    efficiency.loc[efficiency["fuel"].isin([fuel])],
                    dims=["region", "vintage"],
                    value_col="efficiency",
                )
                for fuel in spec.fuels
            },
            notes=parameters.efficiency_notes,
            data_quality=DataQualityProfile(cred=1, geog=1, struc=1, tech=1, time=3),
            units=f"{end_use.demand_units()}/PJ",
        )
        .with_existing_capacities(
            RegionVintageArray(regions, vintages).fill_from_df(
                capacity, dims=["region", "vintage"], value_col="capacity"
            ),
            notes=parameters.existing_capacity_notes,
            data_quality=DataQualityProfile(cred=1, geog=1, struc=1, tech=1, time=3),
            units=end_use.capacity_units(),
        )
        .with_capacity_to_activity(
            RegionalValuesArray(regions, fill=1.0),
            units=f"{end_use.demand_units()}/{end_use.capacity_units()}.y",
        )
        .with_lifetimes(
            RegionalValuesArray(regions).fill_from_df(
                lifetime, dims=["region"], value_col="lifetime"
            ),
            notes=parameters.lifetime_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=3, time=3),
        )
    )
    for operator in (OperatorCode.GE, OperatorCode.LE):
        factors = capacity_factor.loc[capacity_factor["operator"].isin([operator])]
        if factors.empty:
            continue
        entity = entity.with_limit_annual_capacity_factor(
            RegionVintageArray(regions, vintages).fill_from_df(
                factors, dims=["region", "vintage"], value_col="factor"
            ),
            operator=operator,
            notes=parameters.capacity_factor_notes,
            data_quality=DataQualityProfile(cred=1, geog=1, struc=1, tech=1, time=3),
        )
    if not fixed_cost.empty:
        entity = entity.with_fixed_costs(
            RegionVintagePeriodArray(regions, vintages, model_periods).fill_from_df(
                fixed_cost, dims=["region", "vintage", "period"], value_col="cost"
            ),
            notes=parameters.fixed_cost_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=3, time=3),
            units=f"M$/{end_use.capacity_units()}.y",
        )

    name = entity.to_technology_entities()[0].name
    assert name == technology.value, f"{technology.value} would be named {name}"
    return entity


def build_existing_technologies(
    technologies: list[ExistingTechnology],
    parameters: ExistingTechnologyParameters,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> list[FuelServingTechnologyEntity]:
    """
    The existing technologies of `technologies` with existing capacity somewhere,
    in order (see `build_existing_technology`); those without are left out.
    """
    entities = [
        build_existing_technology(
            technology, parameters, provinces, model_periods, data_id
        )
        for technology in technologies
    ]
    return [entity for entity in entities if entity is not None]


@dataclass(frozen=True)
class NewTechnologyParameters:
    """
    Parameters of new technologies (any number of them), one long frame per
    parameter with a `technology` column (`NewTechnology`), and the notes of each
    parameter's rows. Every frame has a `region` column (`CANOEProvince`); vintages
    are model periods.

    Parameters
    ----------
    efficiency : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `end_use` (`ResidentialEndUse`)
        and `efficiency`: output (in the demand units of the end use) per PJ of
        input, one row per end use the technology serves.
    investment_cost : pd.DataFrame
        Columns `region`, `technology`, `vintage` and `cost` (M$ per unit of
        capacity).
    fixed_cost : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `period` and `cost` (M$ per unit of
        capacity and year); periods while the vintage is alive. A technology without
        rows has no fixed cost.
    lifetime : pd.DataFrame
        Columns `region`, `technology` and `lifetime` (years).
    capacity_factor : pd.DataFrame
        Columns `region`, `technology`, `vintage`, `end_use`, `operator`
        (`OperatorCode`) and `factor` (0-1), for each end use the technology serves.
    efficiency_notes, investment_cost_notes, fixed_cost_notes, lifetime_notes,
    capacity_factor_notes : str
        Notes of the rows of each parameter.
    """

    efficiency: pd.DataFrame
    investment_cost: pd.DataFrame
    fixed_cost: pd.DataFrame
    lifetime: pd.DataFrame
    capacity_factor: pd.DataFrame
    efficiency_notes: str
    investment_cost_notes: str
    fixed_cost_notes: str
    lifetime_notes: str
    capacity_factor_notes: str


@dataclass
class NewTechnologyEntity:
    """
    A new residential technology and the commodity it takes, in build order: the
    sector's fuel commodity (e.g. `R_ng`), or the free source commodity `R_ethos` of
    the solar water heater.
    """

    input_commodity: FuelCommodityEntity | SourceCommodityEntity
    technology: TechnologyEntity

    def build(self, db_conn: Connection):
        """
        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        self.input_commodity.build(db_conn)
        self.technology.build(db_conn)


def build_new_technology(
    technology: NewTechnology,
    parameters: NewTechnologyParameters,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> NewTechnologyEntity | None:
    """
    The new technology `technology`, buildable in every model period: annual, with
    limited capacity, a capacity to activity of 1 and one output per end use it
    serves (heat pumps serve space heating and cooling, with an efficiency each).
    Its input is the residential commodity of its fuel, or `R_ethos` for the solar
    water heater (no fuel, see `RESIDENTIAL_MODULE_BUGS.md`).

    The technology is written in the regions with an efficiency and a capacity
    factor for every end use it serves (rows of `parameters` in other regions are
    ignored); regions with an efficiency but no capacity factor are logged (their
    equivalent existing technology has no stock there). None if no region is left.

    params:
    - parameters: see `NewTechnologyParameters`; only the rows of `technology` are
      read. Not modified.
    - model_periods: vintages, and periods of the fixed costs

    Raises
    ------
    ValueError
        For lamps, which also need lifetimes by vintage (stage 4).
    """
    spec = technology.spec()
    if spec.lamp is not None:
        raise ValueError(f"{technology.value} is a lamp: lamps are not built here")

    # NOTE: enum columns are filtered with `isin` (see `build_end_use_demand`)
    def rows_of(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[frame["technology"].isin([technology])]

    def regions_with(frame: pd.DataFrame) -> set[CANOEProvince]:
        """Regions with rows for every end use of the technology"""
        return set.intersection(
            *(
                set(frame.loc[frame["end_use"].isin([end_use]), "region"])
                for end_use in spec.end_uses
            )
        )

    efficiency = rows_of(parameters.efficiency)
    capacity_factor = rows_of(parameters.capacity_factor)
    with_efficiency = regions_with(efficiency)
    with_capacity_factor = regions_with(capacity_factor)
    regions = [p for p in provinces if p in with_efficiency & with_capacity_factor]
    left_out = [p for p in provinces if p in with_efficiency - with_capacity_factor]
    if left_out:
        logger.info(
            f"{spec.name} left out of {', '.join(p.short() for p in left_out)}: no "
            + "annual capacity factor (no stock of its equivalent existing technology)"
        )
    if not regions:
        return None

    def in_regions(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[frame["region"].isin(regions)]

    efficiency = in_regions(efficiency)
    capacity_factor = in_regions(capacity_factor)
    investment_cost = in_regions(rows_of(parameters.investment_cost))
    fixed_cost = in_regions(rows_of(parameters.fixed_cost))
    lifetime = in_regions(rows_of(parameters.lifetime))

    input_commodity = (
        SourceCommodityEntity(
            name=source_commodity_name(),
            description="dummy input - residential",
            data_id=data_id,
            units="PJ",
        )
        if spec.fuel is None
        else FuelCommodityEntity(
            sector=CANOESector.Residential,
            fuel=spec.fuel,
            flag=fuel_commodity_flag(spec.fuel),
            data_id=data_id,
        )
    )
    # Capacity is in the units of the end uses it serves (heat pumps: kunit for both)
    capacity_units = spec.end_uses[0].capacity_units()
    entity = (
        TechnologyEntity(
            name=spec.name,
            output_commodity=end_use_demand_name(spec.end_uses[0]),
            data_id=data_id,
            description=" - ".join(
                [
                    "+".join(e.get_desc_name() for e in spec.end_uses),
                    technology.value,
                    "new",
                ]
            ),
            sector=CANOESector.Residential,
        )
        .set_annual()
        .with_capacity_to_activity(
            RegionalValuesArray(regions, fill=1.0),
            units=f"{spec.end_uses[0].demand_units()}/{capacity_units}.y",
        )
        .with_lifetime(
            RegionalValuesArray(regions).fill_from_df(
                lifetime, dims=["region"], value_col="lifetime"
            ),
            notes=parameters.lifetime_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
        )
        .with_investment_cost(
            RegionVintageArray(regions, model_periods).fill_from_df(
                investment_cost, dims=["region", "vintage"], value_col="cost"
            ),
            notes=parameters.investment_cost_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
            units=f"M$/{capacity_units}",
        )
    )
    for end_use in spec.end_uses:
        output = end_use_demand_name(end_use)
        entity = entity.with_efficiency(
            input_commodity.name,
            RegionVintageArray(regions, model_periods).fill_from_df(
                efficiency.loc[efficiency["end_use"].isin([end_use])],
                dims=["region", "vintage"],
                value_col="efficiency",
            ),
            output_commodity=output,
            notes=parameters.efficiency_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
            units=f"{end_use.demand_units()}/PJ",
        )
        for operator in (OperatorCode.GE, OperatorCode.LE):
            factors = capacity_factor.loc[
                capacity_factor["end_use"].isin([end_use])
                & capacity_factor["operator"].isin([operator])
            ]
            if factors.empty:
                continue
            entity = entity.with_limit_annual_capacity_factor(
                RegionVintageArray(regions, model_periods).fill_from_df(
                    factors, dims=["region", "vintage"], value_col="factor"
                ),
                operator=operator,
                output_commodity=output,
                notes=parameters.capacity_factor_notes,
                data_quality=DataQualityProfile(
                    cred=1, geog=1, struc=3, tech=3, time=3
                ),
            )
    if not fixed_cost.empty:
        entity = entity.with_fixed_cost(
            RegionVintagePeriodArray(
                regions, model_periods, model_periods
            ).fill_from_df(
                fixed_cost, dims=["region", "vintage", "period"], value_col="cost"
            ),
            notes=parameters.fixed_cost_notes,
            data_quality=DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=3),
            units=f"M$/{capacity_units}.y",
        )
    return NewTechnologyEntity(input_commodity=input_commodity, technology=entity)


def build_new_technologies(
    technologies: list[NewTechnology],
    parameters: NewTechnologyParameters,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> list[NewTechnologyEntity]:
    """
    The new technologies of `technologies` written in some region, in order (see
    `build_new_technology`); those left out of every region are logged.
    """
    entities: list[NewTechnologyEntity] = []
    for technology in technologies:
        entity = build_new_technology(
            technology, parameters, provinces, model_periods, data_id
        )
        if entity is None:
            logger.info(f"{technology.spec().name} left out: no region has its data")
            continue
        entities.append(entity)
    return entities

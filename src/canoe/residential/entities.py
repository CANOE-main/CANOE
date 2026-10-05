"""
Temoa objects of the residential sector.

Takes the parameters computed in `build.py` (tidy frames, see each function) and
turns them into `canoe_objects` entities. Nothing in here touches the database; the
caller decides when to `.build()` the returned entities (the demands first, as the
technologies output them).

Built in stages: the demands and the existing technologies (here), then the new
technologies and lighting.
"""

from dataclasses import dataclass

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.demand import (
    DemandEntity,
    DemandSeriesArray,
    DemandSpecificDistributionArray,
)
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.naming import (
    DatasetIdentifier,
    TechnologyCapacityScope,
    get_commodity_name,
)
from canoe.common.time_slices import TimeSlice

from .end_uses import ResidentialEndUse
from .technology_catalog import ExistingTechnology


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

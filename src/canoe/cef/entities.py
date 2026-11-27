"""
Temoa objects of a CEF sector: the sector demand and the technology serving it.

Takes the parameters computed in `build.py` (tidy frames, see each function) and turns
them into `canoe_objects` entities. Nothing in here touches the database; the caller
decides when to `.build()` the returned entities (the demand first, as the technology
outputs its commodity).

The sector is a single technology (e.g. `T_TRP`) with unlimited capacity that turns
the sector fuels into the sector demand (e.g. `T_D_TRP`) with efficiency 1, so the
demand is the energy the sector uses; annual input splits fix the fuel mix of each
period.
"""

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
)
from canoe.canoe_objects.demand import DemandEntity, DemandSeriesArray
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier, get_commodity_name


def cef_demand_name(sector: CANOESector) -> str:
    """
    Name of the demand commodity of a CEF sector: the sector code is its short
    description, as in the technology name (e.g. `T_TRP`).

    Examples
    --------
    >>> cef_demand_name(CANOESector.Transportation)
    'T_D_TRP'
    """
    return get_commodity_name(sector, sector.value, is_demand=True)


def build_cef_demand(
    sector: CANOESector,
    demand: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    notes: str,
    data_id: DatasetIdentifier,
) -> DemandEntity:
    """
    params:
    - demand: sector energy demand, one row per (region, period) with columns
      `region` (`CANOEProvince`), `period` and `demand` (PJ). Not modified.
    - notes: notes of the demand rows
    """
    demand_series = DemandSeriesArray(
        region=provinces, period=model_periods
    ).fill_from_df(demand, dims=["region", "period"], value_col="demand")
    return DemandEntity(
        name=cef_demand_name(sector),
        commodity_description=f"demand for {sector.name.lower()} energy",
        unit="PJ",
        data_id=data_id,
    ).with_demand_series(demand_series, notes=notes)


def build_cef_technology(
    sector: CANOESector,
    splits: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    lifetime: int,
    input_split_operator: OperatorCode,
    split_notes: str,
    data_id: DatasetIdentifier,
) -> FuelServingTechnologyEntity:
    """
    The technology of a CEF sector, taking the fuels with a split as inputs.

    A fuel is an input of a province wherever it has a split, zero splits included:
    the zero keeps the fuel out in that period with the `le` and `e` operators (a
    fuel without a split would be unbounded). The technology has a single vintage,
    the first model period, with efficiency 1 and a `lifetime` reaching the end of
    the horizon.

    params:
    - splits: share of each fuel in the sector energy demand, one row per (region,
      period, fuel) with columns `region` (`CANOEProvince`), `period`, `fuel`
      (`CANOEFuel`) and `split` (0-1). Not modified.
    - lifetime: lifetime of the single vintage, in years
    - input_split_operator: operator of the input splits
    - split_notes: notes of the input split rows
    """
    # NOTE: fuel columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== CANOEFuel.X` compares against str(CANOEFuel.X) (the name) and never matches.
    fuels = [fuel for fuel in CANOEFuel if bool(splits["fuel"].isin([fuel]).any())]
    splits_by_fuel: dict[CANOEFuel, pd.DataFrame] = {
        fuel: splits.loc[splits["fuel"].isin([fuel])] for fuel in fuels
    }

    # Efficiency 1 in the provinces taking the fuel, for the first period's vintage
    first_period = model_periods[0]
    efficiencies = {
        fuel: RegionVintageArray(region=provinces, vintage=[first_period]).fill_from_df(
            splits_by_fuel[fuel]
            .loc[splits_by_fuel[fuel]["period"] == first_period]
            .rename(columns={"period": "vintage"})
            .assign(efficiency=1.0),
            value_col="efficiency",
        )
        for fuel in fuels
    }
    input_splits = {
        fuel: RegionPeriodArray(region=provinces, period=model_periods).fill_from_df(
            splits_by_fuel[fuel], value_col="split"
        )
        for fuel in fuels
    }

    return (
        FuelServingTechnologyEntity(
            sector=sector,
            short_desc=sector.value,
            fuels=fuels,
            fuel_import_flag={
                fuel: CommodityTypeCode.P
                if fuel == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for fuel in fuels
            },
            output_commodity_name=cef_demand_name(sector),
            description=f"all {sector.name.lower()} energy demands",
            grouping=FuelGrouping.Shared,
            data_id=data_id,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiencies(
            efficiencies,
            notes="Dummy tech. Demand equal to the sector energy use",
            units="PJ/PJ",
        )
        .with_lifetimes(
            RegionalValuesArray(region=provinces, fill=lifetime),
            notes="Single vintage serving every period to the end of the horizon",
        )
        .with_input_splits(
            input_splits,
            operator=input_split_operator,
            notes=split_notes,
        )
    )

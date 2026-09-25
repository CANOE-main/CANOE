"""
Temoa objects of the agriculture sector: the demand and the technology serving it.

Takes the parameters computed in `build.py` (tidy frames, see each function) and
turns them into `canoe_objects` entities. Nothing in here touches the database; the
caller decides when to `.build()` the returned entities (the demand first, as the
technology outputs its commodity).

The sector is a single technology (`A_AGRI`) with unlimited capacity that turns the
agriculture fuels into the agriculture demand with efficiency 1, so the demand is the
energy agriculture uses; annual input splits fix the fuel mix.
"""

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode

from canoe.canoe_objects.array_types import RegionPeriodArray, RegionVintageArray
from canoe.canoe_objects.demand import DemandEntity, DemandSeriesArray
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.naming import DatasetIdentifier, get_commodity_name

# Short description in the names of the technology (A_AGRI) and demand (A_D_AGRI)
_SHORT_DESC = "AGRI"


def agriculture_demand_name() -> str:
    """
    Name of the agriculture demand commodity.

    Examples
    --------
    >>> agriculture_demand_name()
    'A_D_AGRI'
    """
    return get_commodity_name(CANOESector.Agriculture, _SHORT_DESC, is_demand=True)


def build_agriculture_demand(
    demand: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    notes: str,
    data_id: DatasetIdentifier,
) -> DemandEntity:
    """
    params:
    - demand: agriculture energy demand, one row per (region, period) with columns
      `region` (`CANOEProvince`), `period` and `demand` (PJ). Not modified.
    - notes: notes of the demand rows
    """
    demand_series = DemandSeriesArray(
        region=provinces, period=model_periods
    ).fill_from_df(demand, dims=["region", "period"], value_col="demand")
    return DemandEntity(
        name=agriculture_demand_name(),
        commodity_description="demand for agriculture energy",
        unit="PJ",
        data_id=data_id,
    ).with_demand_series(
        demand_series,
        notes=notes,
        data_quality=DataQualityProfile(cred=1, geog=1, struc=2, tech=3, time=2),
    )


def build_agriculture_technology(
    input_splits: pd.DataFrame,
    fuels: list[CANOEFuel],
    provinces: list[CANOEProvince],
    model_periods: list[int],
    input_split_operator: OperatorCode,
    split_notes: str,
    data_id: DatasetIdentifier,
) -> FuelServingTechnologyEntity:
    """
    The agriculture technology, taking `fuels` as inputs.

    A fuel is an input of a province in a period only where its split is positive:
    rows with a zero (or missing) split get neither an efficiency nor a split, and
    fuels no province uses are left out of the technology (and of its fuel
    commodities). Efficiencies are 1 with the period as vintage.

    params:
    - input_splits: share of each fuel in the agriculture energy use, one row per
      (region, period, fuel) with columns `region` (`CANOEProvince`), `period`,
      `fuel` (`CANOEFuel`) and `split` (0-1). Not modified.
    - fuels: fuels requested in the config, in order
    - input_split_operator: operator of the input splits
    - split_notes: notes of the input split rows
    """
    # NOTE: fuel columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== CANOEFuel.X` compares against str(CANOEFuel.X) (the name) and never matches.
    used: pd.DataFrame = input_splits.loc[input_splits["split"] > 0]
    used_by_fuel: dict[CANOEFuel, pd.DataFrame] = {
        fuel: used.loc[used["fuel"].isin([fuel])] for fuel in fuels
    }
    technology_fuels = [fuel for fuel in fuels if not used_by_fuel[fuel].empty]

    # Efficiency 1 wherever a fuel is used, with the period as vintage
    efficiencies = {
        fuel: RegionVintageArray(region=provinces, vintage=model_periods).fill_from_df(
            used_by_fuel[fuel]
            .rename(columns={"period": "vintage"})
            .assign(efficiency=1.0),
            value_col="efficiency",
        )
        for fuel in technology_fuels
    }
    splits = {
        fuel: RegionPeriodArray(region=provinces, period=model_periods).fill_from_df(
            used_by_fuel[fuel], value_col="split"
        )
        for fuel in technology_fuels
    }

    return (
        FuelServingTechnologyEntity(
            sector=CANOESector.Agriculture,
            short_desc=_SHORT_DESC,
            fuels=technology_fuels,
            fuel_import_flag={
                f: CommodityTypeCode.P
                if f == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for f in technology_fuels
            },
            output_commodity_name=agriculture_demand_name(),
            grouping=FuelGrouping.Shared,
            data_id=data_id,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiencies(
            efficiencies,
            notes="Dummy tech. Demand equal to agriculture energy use",
        )
        .with_input_splits(
            splits,
            operator=input_split_operator,
            notes=split_notes,
            data_quality=DataQualityProfile(cred=2, geog=1, struc=2, tech=3, time=3),
        )
    )

"""
Technologies serving the commercial `other` end use (everything except space heating
and cooling).

Takes the `other` secondary energy use estimated in `build.py` and turns it into a
`FuelServingTechnologyEntity`. Nothing in here touches the database; the caller decides
when to `.build()` the returned entity.

The demand equals the secondary energy use, so the technologies have efficiency 1 and
unlimited capacity. With the shared grouping, annual input splits fix the fuel mix to
the base-year shares, optionally shifting linearly towards electricity.
"""

from typing import TYPE_CHECKING

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode

from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.canoe_objects.technology import RegionPeriodArray, RegionVintageArray
from canoe.common import CANOEFuel, CANOEProvince, CANOESector, DataQualityProfile
from canoe.common.naming import DatasetIdentifier, get_commodity_name

if TYPE_CHECKING:
    from .config import ElectrificationConfig, OtherEndUseConfig


def build_other_technology(
    other_sec: pd.DataFrame,
    other_config: "OtherEndUseConfig",
    provinces: list[CANOEProvince],
    model_periods: list[int],
    period_end_years: dict[int, int],
    base_year: int,
    data_id: DatasetIdentifier,
) -> FuelServingTechnologyEntity:
    """
    params:
    - other_sec: `other` secondary energy use, one row per (province, fuel) with columns
      `province`, `fuel`, `sec`. Only the fuels that serve the demand. Not modified.
    - model_periods: technologies are available from the first one; input splits are
      written for all of them
    - period_end_years: model period -> year it ends, where the electrification
      trajectory is evaluated
    - base_year: year of the secondary energy use (start of the electrification trajectory)
    """
    fuels = sorted(other_sec["fuel"].unique())
    first_period = model_periods[0]

    # NOTE: fuel columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== CANOEFuel.X` compares against str(CANOEFuel.X) (the name) and never matches.

    # Efficiency 1 for every fuel a province uses, available from the first period
    efficiencies = {
        fuel: RegionVintageArray(region=provinces, vintage=[first_period]).fill_from_df(
            other_sec[other_sec["fuel"].isin([fuel])]
            .rename(columns={"province": "region"})
            .assign(vintage=first_period, efficiency=1.0),
            value_col="efficiency",
        )
        for fuel in fuels
    }

    entity = (
        FuelServingTechnologyEntity(
            sector=CANOESector.Commercial,
            short_desc="OTH",
            fuels=fuels,
            fuel_import_flag={
                f: CommodityTypeCode.P
                if f == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for f in fuels
            },
            output_commodity_name=get_commodity_name(
                CANOESector.Commercial, "OTH", is_demand=True
            ),
            grouping=other_config.technology_grouping,
            data_id=data_id,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiencies(
            efficiencies,
            notes="Dummy tech. Demand equal to secondary energy consumption",
        )
    )

    if other_config.technology_grouping == FuelGrouping.Shared:
        split_notes = (
            f"Secondary energy consumption by fuel (NRCan, {base_year}) "
            "minus space heating and cooling."
        )
        if other_config.electrification:
            split_notes += f" {other_config.electrification.notes}"

        split_df = _compute_input_splits(
            other_sec, period_end_years, base_year, other_config.electrification
        )
        entity = entity.with_input_splits(
            {
                fuel: RegionPeriodArray(
                    region=provinces, period=model_periods
                ).fill_from_df(
                    split_df[split_df["fuel"].isin([fuel])], value_col="split"
                )
                for fuel in fuels
            },
            operator=other_config.input_split_operator,
            notes=split_notes,
            data_quality=DataQualityProfile(cred=1, geog=1, struc=5, tech=1, time=1),
        )
    return entity


def _compute_input_splits(
    other_sec: pd.DataFrame,
    period_end_years: dict[int, int],
    base_year: int,
    electrification: "ElectrificationConfig | None",
) -> pd.DataFrame:
    """
    Fuel shares of each province's `other` energy use, by period.

    With electrification, shares move linearly from the base-year shares (at `base_year`)
    to the target shares (at the end of the last period):
    - electricity: factor + share * (1 - factor)
    - other fuels: share * (1 - factor)

    Returns region, fuel, period, split
    """
    shares = other_sec.rename(columns={"province": "region"}).assign(
        share=lambda df: df["sec"] / df.groupby("region")["sec"].transform("sum")
    )
    periods = pd.DataFrame(
        {"period": list(period_end_years), "end_year": list(period_end_years.values())}
    )
    splits = shares.merge(periods, how="cross")

    if electrification is None:
        return splits.assign(split=splits["share"])[
            ["region", "fuel", "period", "split"]
        ]

    factor = electrification.factor
    last_end_year = max(period_end_years.values())
    progress = (splits["end_year"] - base_year) / (last_end_year - base_year)
    target = (splits["share"] * (1 - factor)).where(
        ~splits["fuel"].isin([CANOEFuel.Electricity]),
        factor + splits["share"] * (1 - factor),
    )
    splits["split"] = splits["share"] + (target - splits["share"]) * progress
    return splits[["region", "fuel", "period", "split"]]

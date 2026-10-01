"""
Temoa objects of the industry sector: a demand and a technology per subsector, and
the free supply of "Other" fuels.

Takes the parameters computed in `build.py` (tidy frames, see each function) and
turns them into `canoe_objects` entities. Nothing in here touches the database; the
caller decides when to `.build()` the returned entities (the demands first, as the
technologies output them, and the free supply last, as it outputs the `I_oth` the
technologies register).

Each subsector is a technology (e.g. `I_PULP`) with unlimited capacity that turns
the industry fuels into the subsector's demand (`I_D_PULP`) with efficiency 1, so
the demand is the energy the subsector uses; annual input splits fix the fuel mix.

With `other_fuels = "free"`, "Other" fuels (`I_oth`) are an input too. The fuel
module has no price or emission factors for them, so they are not a fuel import:

```
I_ethos ──I_FREE_OTH──▶ I_oth ──I_<SUBSECTOR>──▶ I_D_<SUBSECTOR>
 source    no cost,      fuel
           no emissions
```
"""

from collections.abc import Iterable
from dataclasses import dataclass
from sqlite3 import Connection

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
)
from canoe.canoe_objects.commodity import SourceCommodityEntity
from canoe.canoe_objects.demand import DemandEntity, DemandSeriesArray
from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import (
    CANOEFuel,
    CANOEFuelImport,
    CANOEProvince,
    CANOESector,
    DataQualityProfile,
)
from canoe.common.naming import (
    DatasetIdentifier,
    get_commodity_name,
    get_fuel_commodity_in_sector,
)

from .subsectors import IndustrySubsector

SOURCE_COMMODITY = "I_ethos"
"""Source commodity of the free supply of "Other" fuels."""

FREE_OTHER_SUPPLY = "I_FREE_OTH"
"""Technology supplying "Other" fuels (`I_oth`) at no cost and with no emissions."""


def subsector_demand_name(subsector: IndustrySubsector) -> str:
    """
    Name of the demand commodity of an industry subsector.

    Examples
    --------
    >>> subsector_demand_name(IndustrySubsector.OtherManufacturing)
    'I_D_OTH_MAN'
    """
    return get_commodity_name(
        CANOESector.Industry, subsector.short_desc(), is_demand=True
    )


def build_subsector_demand(
    subsector: IndustrySubsector,
    demand: pd.DataFrame,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    notes: str,
    data_id: DatasetIdentifier,
) -> DemandEntity:
    """
    The demand of `subsector`, written where it is positive: a province where the
    subsector uses no energy gets no demand rows.

    params:
    - demand: industry energy demand, one row per (region, period, subsector) with
      columns `region` (`CANOEProvince`), `period`, `subsector`
      (`IndustrySubsector`) and `demand` (PJ); only the rows of `subsector` are
      read. Not modified.
    - notes: notes of the demand rows
    """
    # NOTE: enum columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== IndustrySubsector.X` compares against str(IndustrySubsector.X) (the name)
    # and never matches.
    rows = demand.loc[demand["subsector"].isin([subsector]) & (demand["demand"] > 0)]
    demand_series = DemandSeriesArray(
        region=provinces, period=model_periods
    ).fill_from_df(rows, dims=["region", "period"], value_col="demand")
    return DemandEntity(
        name=subsector_demand_name(subsector),
        commodity_description=f"demand for {subsector.get_desc_name()} energy",
        unit="PJ",
        data_id=data_id,
    ).with_demand_series(
        demand_series,
        notes=notes,
        data_quality=DataQualityProfile(cred=1, geog=1, struc=2, tech=3, time=2),
    )


def build_subsector_technology(
    subsector: IndustrySubsector,
    input_splits: pd.DataFrame,
    fuels: list[CANOEFuel],
    provinces: list[CANOEProvince],
    model_periods: list[int],
    input_split_operator: OperatorCode,
    split_notes: str,
    data_id: DatasetIdentifier,
) -> FuelServingTechnologyEntity:
    """
    The technology of `subsector`, taking `fuels` as inputs.

    A fuel is an input of a province in a period only where its split is positive:
    rows with a zero (or missing) split get neither an efficiency nor a split, and
    fuels no province uses are left out of the technology (and of its fuel
    commodities). Efficiencies are 1 with the period as vintage.

    params:
    - input_splits: share of each fuel in the energy use of each subsector, one row
      per (region, period, subsector, fuel) with columns `region` (`CANOEProvince`),
      `period`, `subsector` (`IndustrySubsector`), `fuel` (`CANOEFuel`) and `split`
      (0-1); only the rows of `subsector` are read. Not modified.
    - fuels: fuels of the subsector, in order (`CANOEFuel.Other` included when
      "Other" fuels are supplied for free)
    - input_split_operator: operator of the input splits
    - split_notes: notes of the input split rows

    Raises
    ------
    ValueError
        If no fuel has a positive split: the technology would have no inputs.
    """
    used: pd.DataFrame = input_splits.loc[
        input_splits["subsector"].isin([subsector]) & (input_splits["split"] > 0)
    ]
    used_by_fuel: dict[CANOEFuel, pd.DataFrame] = {
        fuel: used.loc[used["fuel"].isin([fuel])] for fuel in fuels
    }
    technology_fuels = [fuel for fuel in fuels if not used_by_fuel[fuel].empty]
    if not technology_fuels:
        raise ValueError(
            f"No input splits for {subsector.get_desc_name()}: its technology would "
            + "have no inputs"
        )

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
            sector=CANOESector.Industry,
            short_desc=subsector.short_desc(),
            fuels=technology_fuels,
            fuel_import_flag={
                f: CommodityTypeCode.P
                if f == CANOEFuel.Electricity
                else CommodityTypeCode.A
                for f in technology_fuels
            },
            output_commodity_name=subsector_demand_name(subsector),
            description=f"energy use of the {subsector.get_desc_name()} industry",
            grouping=FuelGrouping.Shared,
            data_id=data_id,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiencies(
            efficiencies,
            notes=f"Dummy tech. Demand equal to {subsector.get_desc_name()} energy use",
        )
        .with_input_splits(
            splits,
            operator=input_split_operator,
            notes=split_notes,
            data_quality=DataQualityProfile(cred=2, geog=1, struc=2, tech=3, time=3),
        )
    )


@dataclass
class FreeOtherFuelSupply:
    """
    The free supply of "Other" fuels, in build order: the source commodity and the
    technology. `I_oth` must already exist (the subsector technologies register it).
    """

    source: SourceCommodityEntity
    technology: TechnologyEntity

    def build(self, db_conn: Connection):
        """
        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        self.source.build(db_conn)
        self.technology.build(db_conn)


def build_free_other_fuel_supply(
    technologies: Iterable[FuelServingTechnologyEntity],
    lifetime: float,
    data_id: DatasetIdentifier,
) -> FreeOtherFuelSupply | None:
    """
    The supply of "Other" fuels (`I_oth`) at no cost and with no emissions, in the
    (region, period) where some subsector technology takes them: a transfer from
    `I_ethos` with efficiency 1, unlimited capacity, annual, with a lifetime of one
    period so each vintage only supplies its own period. None if no technology takes
    "Other" fuels.

    params:
    - technologies: the subsector technologies, see `build_subsector_technology`
    - lifetime: technology lifetime (years), the length of a period
    """
    other = get_fuel_commodity_in_sector(CANOESector.Industry, CANOEFuel.Other)
    cells: set[tuple[CANOEProvince, int]] = set()
    for technology in technologies:
        for entity in technology.to_technology_entities():
            for (input_commodity, _), efficiency in entity.efficiencies.items():
                if input_commodity == other:
                    cells |= {
                        (record["region"], record["vintage"])
                        for record in efficiency.values.to_records()
                    }
    if not cells:
        return None

    used_regions = {region for region, _ in cells}
    regions = [p for p in CANOEProvince if p in used_regions]
    periods = sorted({period for _, period in cells})
    efficiency = RegionVintageArray(regions, periods)
    for region, period in cells:
        efficiency.set(1.0, region=region, vintage=period)

    return FreeOtherFuelSupply(
        source=SourceCommodityEntity(
            name=SOURCE_COMMODITY,
            description="supply point of the industry fuels with no fuel import",
            data_id=data_id,
        ),
        technology=TechnologyEntity(
            name=FREE_OTHER_SUPPLY,
            output_commodity=other,
            data_id=data_id,
            description="other fuels of the industry, at no cost and with no "
            + "emissions (no price or emission factors for them)",
            sector=CANOESector.Industry,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiency(
            SOURCE_COMMODITY,
            efficiency,
            notes="Free supply of NRCan CEUD 'Other' industry fuels: the fuel module "
            + "has no price or emission factors for them (see INDUSTRY_MODULE_BUGS.md)",
        )
        .with_lifetime(
            RegionalValuesArray(regions, fill=lifetime),
            notes="One period, so each vintage only supplies its own period",
        ),
    )


def industry_fuel_imports(
    technologies: Iterable[FuelServingTechnologyEntity],
) -> list[CANOEFuelImport]:
    """
    The fuels the subsector technologies take, where they take them, for the fuel
    module to supply. "Other" fuels are left out: the industry supplies them itself
    (see `build_free_other_fuel_supply`).
    """
    return [
        fuel_import
        for fuel_import in declare_fuel_imports(
            CANOESector.Industry,
            [e for t in technologies for e in t.to_technology_entities()],
        )
        if fuel_import.fuel != CANOEFuel.Other
    ]


@dataclass
class IndustryEntities:
    """
    Everything the industry sector writes, in build order: the subsector demands,
    the subsector technologies and, if any technology takes "Other" fuels, their
    free supply.
    """

    demands: list[DemandEntity]
    technologies: list[FuelServingTechnologyEntity]
    free_other_supply: FreeOtherFuelSupply | None

    def build(self, db_conn: Connection):
        """
        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        for demand in self.demands:
            demand.build(db_conn)
        for technology in self.technologies:
            technology.build(db_conn)
        if self.free_other_supply is not None:
            self.free_other_supply.build(db_conn)

    def fuel_imports(self) -> list[CANOEFuelImport]:
        """The fuels the fuel module supplies, see `industry_fuel_imports`"""
        return industry_fuel_imports(self.technologies)


def build_industry_entities(
    demand: pd.DataFrame,
    input_splits: pd.DataFrame,
    input_fuels_of: dict[IndustrySubsector, list[CANOEFuel]],
    provinces: list[CANOEProvince],
    model_periods: list[int],
    input_split_operator: OperatorCode,
    demand_notes: str,
    split_notes: str,
    lifetime: float,
    data_id: DatasetIdentifier,
) -> IndustryEntities:
    """
    A demand and a technology for each subsector of `input_fuels_of` with a positive
    demand somewhere (the others are left out), and the free supply of "Other"
    fuels if some technology takes them.

    params:
    - demand, input_splits: see `build_subsector_demand` and
      `build_subsector_technology`; every (region, subsector) with a positive demand
      needs a positive split (see `demand.align_demand_and_splits`)
    - input_fuels_of: inputs of each subsector's technology, in order
    - demand_notes, split_notes: notes of the demand and input split rows
    - lifetime: lifetime of the free supply of "Other" fuels (years), a period
    """
    modelled = [
        subsector
        for subsector in input_fuels_of
        if (demand["subsector"].isin([subsector]) & (demand["demand"] > 0)).any()
    ]
    demands = [
        build_subsector_demand(
            subsector, demand, provinces, model_periods, demand_notes, data_id
        )
        for subsector in modelled
    ]
    technologies = [
        build_subsector_technology(
            subsector,
            input_splits,
            input_fuels_of[subsector],
            provinces,
            model_periods,
            input_split_operator,
            split_notes,
            data_id,
        )
        for subsector in modelled
    ]
    return IndustryEntities(
        demands=demands,
        technologies=technologies,
        free_other_supply=build_free_other_fuel_supply(technologies, lifetime, data_id),
    )

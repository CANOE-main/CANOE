"""
Temoa objects of the generators: existing (`-EXS`), new (`-NEW`) and the new wind and
solar resource bins (`-NEW-<n>`), one technology per `GenerationTechnology` (and
bin):

    E_<fuel> or E_ethos --<TECH>-EXS/-NEW--> E_elc_tx or E_elc_dx

Existing monthly hydro is split in two around its reservoir, so the water can be
generated in another season than it arrives in:

    E_ethos --E_HYD_MLY-EXS-IN--> E_hyd_mly_stor --E_HYD_MLY-EXS--> E_elc_tx

`-IN` is the inflow (baseload, no costs, not in the reserve); `-EXS` the turbine and
the reservoir, a seasonal storage of 730 hours (a month) at full output.
"""

from dataclasses import dataclass, field
from sqlite3 import Connection
from typing import cast

import numpy as np
import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode, TechnologyTypeCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionSeasonArray,
    RegionSeasonTodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
    RegionVintageSeasonArray,
    RegionVintageSeasonTodArray,
)
from canoe.canoe_objects.commodity import (
    FuelCommodityEntity,
    PhysicalCommodityEntity,
    SourceCommodityEntity,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEEmission, CANOEProvince, CANOESector
from canoe.common.naming import (
    DatasetIdentifier,
    get_emission_commodity_name,
    get_fuel_commodity_in_sector,
)
from canoe.common.time_slices import hour_to_day, hour_to_tod

from ..catalogue import CCSRetrofit, GenerationTechnology
from .parameters import Technology


def source_commodity_name() -> str:
    """
    Free resources of the generators (water, wind, sun, heat).

    Examples
    --------
    >>> source_commodity_name()
    'E_ethos'
    """
    return f"{CANOESector.Electricity.get_tag()}_ethos"


@dataclass(frozen=True)
class GenerationNotes:
    """
    Notes of the rows of the generators.

    Parameters
    ----------
    capacity : str
        How the CODERS units are grouped into vintages.
    atb_costs, coders_costs : str
        Source and currency of the ATB and CODERS costs.
    atb_efficiency : str
        Source of the ATB heat rates.
    cogeneration : str
        Source and meaning of the cogeneration activity limits.
    vre_bin_costs, vre_bin_limits, vre_bin_capacity_factors : str
        Source (and currency) of the costs, capacity limits and capacity factors of
        the wind and solar bins.
    vre_capacity_factors, hydro_capacity_factors : str
        Source of the capacity factors of the existing wind and solar, and hydro.
    capture : str
        How the CO2 captured is computed.
    capacity_credits, reserve_derates, vre_bin_capacity_credits : str
        Source of the capacity credits and reserve capacity derates, and of the
        capacity credits of the wind and solar bins.
    ramp_rates : str
        Source of the ramp rates.
    """

    capacity: str
    atb_costs: str
    coders_costs: str
    atb_efficiency: str
    cogeneration: str
    vre_bin_costs: str
    vre_bin_limits: str
    vre_bin_capacity_factors: str
    vre_capacity_factors: str
    hydro_capacity_factors: str
    capture: str
    capacity_credits: str
    reserve_derates: str
    vre_bin_capacity_credits: str
    ramp_rates: str


@dataclass
class GenerationEntities:
    """The commodities and technologies of a set of generators."""

    commodities: list[
        FuelCommodityEntity | SourceCommodityEntity | PhysicalCommodityEntity
    ] = field(default_factory=list)
    technologies: list[TechnologyEntity] = field(default_factory=list)

    def build(self, db_conn: Connection):
        """Write the commodities first, then the technologies that use them."""
        for commodity in self.commodities:
            commodity.build(db_conn)
        for technology in self.technologies:
            technology.build(db_conn)


@dataclass(frozen=True)
class CarbonCapture:
    """
    How the generators connect to carbon capture.

    Parameters
    ----------
    outputs : dict[GenerationTechnology, str]
        Generators whose output goes to the intermediate commodity of their CCS
        retrofits (see `retrofit_intermediate_commodity`) instead of the grid.
    factors : dict[GenerationTechnology, float]
        CO2 captured per unit of fuel burned (negative, kt/PJ) by the generators built
        with capture, see `generation.ccs.generator_capture_factors`.
    """

    outputs: dict[GenerationTechnology, str] = field(default_factory=dict)
    factors: dict[GenerationTechnology, float] = field(default_factory=dict)


def _no_rows(*columns: str) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


@dataclass(frozen=True)
class Reliability:
    """
    What the generators count towards the planning reserve margin, and how fast
    they ramp. Empty frames leave the generators out of the reserve margin (Temoa's
    defaults: no capacity credit, a derate of 1).

    Parameters
    ----------
    credits : pd.DataFrame
        Capacity credits, see `reliability.process_capacity_credits`.
    derates : pd.DataFrame
        Reserve capacity derates, see `reliability.process_reserve_derates`.
    bin_credits : pd.DataFrame
        Capacity credits of the wind and solar bins, see
        `reliability.vre_bin_capacity_credits`.
    ramp_rates : pd.DataFrame
        Hourly ramp rates (up and down), columns `technology` and `rate`, see
        `loaders.get_ramp_rates`.
    """

    credits: pd.DataFrame = field(
        default_factory=lambda: _no_rows(
            "region", "technology", "vintage", "period", "credit"
        )
    )
    derates: pd.DataFrame = field(
        default_factory=lambda: _no_rows("region", "technology", "vintage", "factor")
    )
    bin_credits: pd.DataFrame = field(
        default_factory=lambda: _no_rows(
            "region", "technology", "bin", "vintage", "period", "credit"
        )
    )
    ramp_rates: pd.DataFrame = field(
        default_factory=lambda: _no_rows("technology", "rate")
    )


def retrofit_intermediate_commodity(generator: GenerationTechnology) -> str:
    """
    Commodity between a retrofitted generator and the grid.

    Examples
    --------
    >>> retrofit_intermediate_commodity(GenerationTechnology.NaturalGasCC)
    'E_elc_tx_ng_cc'
    """
    return f"{generator.get_grid_level().get_commodity()}_{generator.value}"


def build_existing_generation(
    fleet: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    efficiencies: pd.DataFrame,
    costs: pd.DataFrame,
    cogeneration: pd.DataFrame,
    capacity_factors: pd.DataFrame,
    seasonal_limits: pd.DataFrame,
    capture: CarbonCapture,
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
    reliability: Reliability | None = None,
) -> GenerationEntities:
    """
    One `-EXS` technology per technology of the fleet, in the regions and vintages
    where it has capacity; monthly hydro also gets its reservoir inflow (`-IN`),
    which carries the monthly hydro's daily limits (and is not in the reserve).

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.
    efficiencies : pd.DataFrame
        See `generation.parameters.process_efficiencies`.
    costs : pd.DataFrame
        See `generation.parameters.process_om_costs`.
    cogeneration : pd.DataFrame
        See `generation.parameters.cogeneration_activity`.
    capacity_factors : pd.DataFrame
        Hourly capacity factors (columns `region`, `technology`, `hour`, `factor`),
        see `generation.capacity_factors`.
    seasonal_limits : pd.DataFrame
        Upper limits on each day's capacity factor (columns `region`, `technology`,
        `day`, `factor`), see `generation.capacity_factors.daily_capacity_factors`.
    capture : CarbonCapture
        Outputs of the retrofitted generators, and capture of those built with it.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    reliability : Reliability, optional
        Capacity credits, derates and ramp rates; none if not given.
    """
    # Monthly hydro reservoir: a month of output at full capacity
    RESERVOIR_HOURS = 730

    reliability = reliability or Reliability()

    technologies: list[GenerationTechnology] = list(dict.fromkeys(fleet["technology"]))
    entities = GenerationEntities(commodities=_commodities(technologies, data_id))
    reservoir = "E_hyd_mly_stor"
    if GenerationTechnology.HydroMonthly in technologies:
        entities.commodities.append(
            PhysicalCommodityEntity(
                name=reservoir,
                description="water in the monthly hydro reservoirs, as the "
                + "electricity it generates",
                data_id=data_id,
            )
        )

    for technology in technologies:
        of_fleet = fleet.loc[fleet["technology"] == technology]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_fleet["region"]))
        vintages = sorted({int(v) for v in of_fleet["vintage"]})
        name = f"{technology.get_tech_code()}-EXS"
        is_reservoir = technology == GenerationTechnology.HydroMonthly
        capacity = region_vintage(of_fleet, "capacity", regions, vintages)

        entity = _generator(
            technology,
            name,
            "existing",
            region_vintage(
                efficiencies.loc[efficiencies["technology"] == technology],
                "efficiency",
                regions,
                vintages,
            ),
            lifetimes[technology],
            notes,
            data_id,
            input_commodity=reservoir if is_reservoir else None,
            capture=capture,
        ).with_existing_capacity(
            capacity,
            notes=notes.capacity
            + (
                "; never retires, so all units are in the last existing vintage"
                if technology.never_retires()
                else ""
            ),
            units="GW",
        )
        if is_reservoir:
            entity.flag = TechnologyTypeCode.PS
            entity.set_seasonal_storage().with_storage_duration(
                RegionalValuesArray(regions, fill=RESERVOIR_HOURS),
                notes="Hours of output at full capacity: about a month",
            )
        with_om_costs(entity, technology, costs, regions, vintages, notes)
        with_reliability(entity, technology, reliability, regions, vintages, notes)

        # Cogeneration output held at its historical level
        of_cogeneration = cogeneration.loc[cogeneration["technology"] == technology]
        if not of_cogeneration.empty:
            limit_periods = sorted({int(p) for p in of_cogeneration["period"]})
            for operator, column in (
                (OperatorCode.GE, "min_activity"),
                (OperatorCode.LE, "max_activity"),
            ):
                activity = RegionPeriodArray(regions, limit_periods)
                for region, period, value in zip(
                    of_cogeneration["region"],
                    of_cogeneration["period"],
                    of_cogeneration[column],
                ):
                    activity.set(float(value), region=region, period=int(period))
                entity.with_limit_activity(
                    activity, operator, notes=notes.cogeneration, units="PJ"
                )

        # Weather: hourly capacity factors, or daily limits (on the inflow of
        # monthly hydro)
        is_hydro = technology in (
            GenerationTechnology.HydroDaily,
            GenerationTechnology.HydroMonthly,
            GenerationTechnology.HydroRunOfRiver,
        )
        factor_notes = (
            notes.hydro_capacity_factors if is_hydro else notes.vre_capacity_factors
        )
        of_factors = capacity_factors.loc[capacity_factors["technology"] == technology]
        if not of_factors.empty:
            entity.with_capacity_factor(
                _hourly_values(of_factors, regions), notes=factor_notes
            )
        of_limits = seasonal_limits.loc[seasonal_limits["technology"] == technology]
        daily_limits = (
            _daily_values(of_limits, regions) if not of_limits.empty else None
        )
        if daily_limits is not None and not is_reservoir:
            entity.with_limit_seasonal_capacity_factor(
                daily_limits, notes=f"Daily average: {factor_notes}"
            )

        entities.technologies.append(entity)

        if is_reservoir:
            inflow = RegionVintageArray(regions, vintages)
            for record in capacity.to_records():
                inflow.set(1.0, region=record["region"], vintage=record["vintage"])
            inflow_entity = (
                TechnologyEntity(
                    name=f"{name}-IN",
                    output_commodity=reservoir,
                    data_id=data_id,
                    description="inflow to reservoir for monthly hydroelectric "
                    + "generation - existing",
                    sector=CANOESector.Electricity,
                    flag=TechnologyTypeCode.PB,
                )
                .with_efficiency(
                    source_commodity_name(),
                    inflow,
                    notes="Water counted as the electricity it generates",
                    units="PJ/PJ",
                )
                .with_existing_capacity(capacity, notes=f"Same as {name}", units="GW")
                .with_lifetime(
                    RegionalValuesArray(regions, fill=lifetimes[technology]),
                    notes=f"Same as {name}",
                )
                .with_capacity_to_activity(
                    RegionalValuesArray(regions, fill=capacity_to_activity()),
                    notes="PJ produced by 1 GW over a year (8760 h)",
                    units="PJ/GWy",
                )
            )
            if daily_limits is not None:
                inflow_entity.with_limit_seasonal_capacity_factor(
                    daily_limits, notes=f"Daily average inflow: {factor_notes}"
                )
            entities.technologies.append(inflow_entity)

    return entities


def build_new_generation(
    efficiencies: pd.DataFrame,
    investment: pd.DataFrame,
    costs: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    capture: CarbonCapture,
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
    reliability: Reliability | None = None,
) -> GenerationEntities:
    """
    One `-NEW` technology per new (not binned) technology, in the regions and
    vintages of `efficiencies`.

    Parameters
    ----------
    efficiencies : pd.DataFrame
        See `generation.parameters.process_efficiencies` (of `new_processes`).
    investment : pd.DataFrame
        See `generation.parameters.process_investment_costs`.
    costs : pd.DataFrame
        See `generation.parameters.process_om_costs`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.
    capture : CarbonCapture
        Outputs of the retrofitted generators, and capture of those built with it.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    reliability : Reliability, optional
        Capacity credits, derates and ramp rates; none if not given.
    """
    reliability = reliability or Reliability()
    technologies: list[GenerationTechnology] = list(
        dict.fromkeys(efficiencies["technology"])
    )
    entities = GenerationEntities(commodities=_commodities(technologies, data_id))
    for technology in technologies:
        of_efficiency = efficiencies.loc[efficiencies["technology"] == technology]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_efficiency["region"]))
        vintages = sorted({int(v) for v in of_efficiency["vintage"]})
        entity = _generator(
            technology,
            f"{technology.get_tech_code()}-NEW",
            "new",
            region_vintage(of_efficiency, "efficiency", regions, vintages),
            lifetimes[technology],
            notes,
            data_id,
            capture=capture,
        ).with_investment_cost(
            region_vintage(
                investment.loc[investment["technology"] == technology],
                "cost",
                regions,
                vintages,
            ),
            notes=f"OCC ({technology.get_atb_display_name()}): {notes.atb_costs}",
            units="M$/GW",
        )
        with_om_costs(entity, technology, costs, regions, vintages, notes)
        with_reliability(entity, technology, reliability, regions, vintages, notes)
        entities.technologies.append(entity)
    return entities


def build_vre_bins(
    investment: pd.DataFrame,
    fixed: pd.DataFrame,
    limits: pd.DataFrame,
    capacity_factors: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
    credits: pd.DataFrame | None = None,
) -> GenerationEntities:
    """
    One technology per new wind and solar resource bin (`<code>-NEW-<n>`), in the
    regions and vintages of its investment costs, limited to the bin's capacity,
    with an hourly capacity factor for each vintage and, if given, its capacity
    credits. No derate: their capacity factor already is their availability.

    Parameters
    ----------
    investment, fixed : pd.DataFrame
        See `generation.parameters.vre_bin_costs`.
    limits : pd.DataFrame
        See `generation.parameters.vre_bin_limits`.
    capacity_factors : pd.DataFrame
        See `generation.parameters.vre_bin_capacity_factors`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    credits : pd.DataFrame, optional
        See `reliability.vre_bin_capacity_credits`; none if not given.
    """
    technologies: list[GenerationTechnology] = list(
        dict.fromkeys(investment["technology"])
    )
    entities = GenerationEntities(commodities=_commodities(technologies, data_id))
    # Millions of rows: grouped once rather than filtered for every bin
    factors_by_bin = dict(
        list(capacity_factors.groupby(["technology", "bin"], sort=False))
    )
    bins = investment[["technology", "bin"]].drop_duplicates()
    for technology, number in zip(bins["technology"], bins["bin"]):
        of_investment = investment.loc[
            (investment["technology"] == technology) & (investment["bin"] == number)
        ]
        of_fixed = fixed.loc[
            (fixed["technology"] == technology) & (fixed["bin"] == number)
        ]
        of_limits = limits.loc[
            (limits["technology"] == technology) & (limits["bin"] == number)
        ]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_investment["region"]))
        vintages = sorted({int(v) for v in of_investment["vintage"]})
        periods = sorted({int(p) for p in of_limits["period"]})
        efficiency = RegionVintageArray(regions, vintages)
        for region, vintage in zip(of_investment["region"], of_investment["vintage"]):
            efficiency.set(1.0, region=region, vintage=int(vintage))
        capacity = RegionPeriodArray(regions, periods)
        for region, period, value in zip(
            of_limits["region"], of_limits["period"], of_limits["capacity"]
        ):
            capacity.set(float(value), region=region, period=int(period))

        entity = (
            _generator(
                technology,
                f"{technology.get_tech_code()}-NEW-{number}",
                f"new - resource bin {number}",
                efficiency,
                lifetimes[technology],
                notes,
                data_id,
            )
            .with_investment_cost(
                region_vintage(of_investment, "cost", regions, vintages),
                notes=f"Investment: {notes.vre_bin_costs}",
                units="M$/GW",
            )
            .with_fixed_cost(
                region_vintage_period(of_fixed, "cost", regions, vintages),
                notes=f"Fixed O&M: {notes.vre_bin_costs}",
                units="M$/GWy",
            )
            .with_limit_capacity(capacity, notes=notes.vre_bin_limits, units="GW")
            .with_capacity_factor_process(
                _hourly_vintage_values(
                    factors_by_bin[(technology, number)], regions, vintages
                ),
                notes=notes.vre_bin_capacity_factors,
            )
        )
        if credits is not None:
            of_credits = credits.loc[
                (credits["technology"] == technology) & (credits["bin"] == number)
            ]
            entity.with_capacity_credit(
                region_vintage_period(of_credits, "credit", regions, vintages),
                notes=notes.vre_bin_capacity_credits,
            )
        entities.technologies.append(entity)
    return entities


def build_ccs_retrofits(
    processes: pd.DataFrame,
    bypasses: pd.DataFrame,
    efficiencies: pd.DataFrame,
    investment: pd.DataFrame,
    costs: pd.DataFrame,
    captures: dict[CCSRetrofit, float],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
) -> GenerationEntities:
    """
    The CCS retrofits and the commodities and bypasses around them. Each retrofitted
    generator outputs to its intermediate commodity (see `CarbonCapture`):

        E_elc_tx_<gen> --<GEN>_RFIT_BYPASS---------> E_elc_tx
                       \\--<GEN>_CCS_RFIT_<rate>---> E_elc_tx  (captures CO2)

    The bypass is free and unlimited; the retrofits are built (one vintage per period
    where a generator can be retrofitted), lose part of the electricity and capture
    part of the CO2 of the fuel burned upstream.

    Parameters
    ----------
    processes, bypasses : pd.DataFrame
        See `generation.ccs.retrofit_processes`.
    efficiencies : pd.DataFrame
        See `generation.ccs.retrofit_efficiencies`.
    investment : pd.DataFrame
        See `generation.parameters.process_investment_costs` (`Additional OCC`).
    costs : pd.DataFrame
        See `generation.ccs.retrofit_om_costs`.
    captures : dict[CCSRetrofit, float]
        See `generation.ccs.retrofit_capture_factors`.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    entities = GenerationEntities()
    for generator in dict.fromkeys(bypasses["generator"]):
        intermediate = retrofit_intermediate_commodity(generator)
        grid = generator.get_grid_level().get_commodity()
        entities.commodities.append(
            PhysicalCommodityEntity(
                name=intermediate,
                description=f"{generator.get_description()}, to the grid either "
                + "directly or through a CCS retrofit",
                data_id=data_id,
            )
        )
        of_bypass = bypasses.loc[bypasses["generator"] == generator]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_bypass["region"]))
        lifetimes = RegionalValuesArray(regions)
        for region, lifetime in zip(of_bypass["region"], of_bypass["lifetime"]):
            lifetimes.set(float(lifetime), region=region)
        first_period = min(int(v) for v in processes["vintage"])
        entities.technologies.append(
            TechnologyEntity(
                name=f"{generator.get_tech_code()}_RFIT_BYPASS",
                output_commodity=grid,
                data_id=data_id,
                description=f"{generator.get_description()} without CCS retrofit",
                sector=CANOESector.Electricity,
            )
            .set_unlimited_capacity()
            .with_efficiency(
                intermediate,
                RegionVintageArray(regions, [first_period], fill=1.0),
                notes="No losses: the generator's output as it is",
                units="PJ/PJ",
            )
            .with_lifetime(
                lifetimes,
                notes="Until the end of life of the last retrofittable generator",
            )
            .with_capacity_to_activity(
                RegionalValuesArray(regions, fill=capacity_to_activity()),
                notes="PJ produced by 1 GW over a year (8760 h)",
                units="PJ/GWy",
            )
        )

        for retrofit in dict.fromkeys(
            r for r in processes["technology"] if r.get_generator() == generator
        ):
            of_retrofit = processes.loc[processes["technology"] == retrofit]
            regions = list(dict.fromkeys(of_retrofit["region"]))
            vintages = sorted({int(v) for v in of_retrofit["vintage"]})
            entity = (
                TechnologyEntity(
                    name=retrofit.get_tech_code(),
                    output_commodity=grid,
                    data_id=data_id,
                    description=retrofit.get_description(),
                    sector=CANOESector.Electricity,
                )
                .with_efficiency(
                    intermediate,
                    region_vintage(
                        efficiencies.loc[efficiencies["technology"] == retrofit],
                        "efficiency",
                        regions,
                        vintages,
                    ),
                    notes=f"1 + net output penalty ({retrofit.get_atb_display_name()})"
                    + f": {notes.atb_efficiency}",
                    units="PJ/PJ",
                )
                .with_lifetime_process(
                    region_vintage(of_retrofit, "lifetime", regions, vintages),
                    notes=f"{generator.get_description()} service life, capped at "
                    + "the end of life of the last retrofittable generator",
                )
                .with_capacity_to_activity(
                    RegionalValuesArray(regions, fill=capacity_to_activity()),
                    notes="PJ produced by 1 GW over a year (8760 h)",
                    units="PJ/GWy",
                )
                .with_investment_cost(
                    region_vintage(
                        investment.loc[investment["technology"] == retrofit],
                        "cost",
                        regions,
                        vintages,
                    ),
                    notes=f"Additional OCC ({retrofit.get_atb_display_name()}): "
                    + notes.atb_costs,
                    units="M$/GW",
                )
                .with_input_emission_factor(
                    get_emission_commodity_name(CANOEEmission.CO2),
                    intermediate,
                    captures[retrofit],
                    notes=f"Captured: {notes.capture}",
                    units="kt/PJ",
                )
            )
            with_om_costs(entity, retrofit, costs, regions, vintages, notes)
            entities.technologies.append(entity)
    return entities


def _commodities(
    technologies: list[GenerationTechnology], data_id: DatasetIdentifier
) -> list[FuelCommodityEntity | SourceCommodityEntity | PhysicalCommodityEntity]:
    """The fuels `technologies` burn, and the free resources if some burn none"""
    fuels = [fuel for t in technologies if (fuel := t.get_input_fuel()) is not None]
    commodities: list[
        FuelCommodityEntity | SourceCommodityEntity | PhysicalCommodityEntity
    ] = [
        FuelCommodityEntity(
            sector=CANOESector.Electricity,
            fuel=fuel,
            flag=CommodityTypeCode.A,
            data_id=data_id,
        )
        for fuel in dict.fromkeys(fuels)
    ]
    if any(t.get_input_fuel() is None for t in technologies):
        commodities.append(
            SourceCommodityEntity(
                name=source_commodity_name(),
                description="free resources of the generators (water, wind, sun, "
                + "heat)",
                data_id=data_id,
                units="PJ",
            )
        )
    return commodities


def _generator(
    technology: GenerationTechnology,
    name: str,
    kind: str,
    efficiency: RegionVintageArray,
    lifetime: int,
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
    input_commodity: str | None = None,
    capture: CarbonCapture | None = None,
) -> TechnologyEntity:
    """
    A generator from its fuel (or `E_ethos`, or `input_commodity`) to its grid level
    (or the intermediate commodity of its CCS retrofits), with its flags, lifetime,
    capacity to activity and, if built with capture, the CO2 it captures.
    """
    fuel = technology.get_input_fuel()
    source = input_commodity or (
        source_commodity_name()
        if fuel is None
        else get_fuel_commodity_in_sector(CANOESector.Electricity, fuel)
    )
    regions: list[CANOEProvince] = list(efficiency.coords["region"])
    capture = capture or CarbonCapture()
    entity = (
        TechnologyEntity(
            name=name,
            output_commodity=capture.outputs.get(
                technology, technology.get_grid_level().get_commodity()
            ),
            data_id=data_id,
            description=f"{technology.get_description()} - {kind}",
            sector=CANOESector.Electricity,
            flag=TechnologyTypeCode.PB
            if technology.is_baseload()
            else TechnologyTypeCode.P,
        )
        .set_reserve()
        .set_curtailable(technology.is_curtailable())
        .with_efficiency(
            source,
            efficiency,
            notes=_efficiency_notes(technology, notes, input_commodity),
            units="PJ/PJ",
        )
        .with_lifetime(
            RegionalValuesArray(regions, fill=lifetime),
            notes="Never retires: kept for the whole horizon"
            if technology.never_retires()
            else "CODERS generation_generic service_life "
            + f"({technology.get_coders_generic_type()})",
        )
        .with_capacity_to_activity(
            RegionalValuesArray(regions, fill=capacity_to_activity()),
            notes="PJ produced by 1 GW over a year (8760 h)",
            units="PJ/GWy",
        )
    )
    if technology in capture.factors:
        entity.with_input_emission_factor(
            get_emission_commodity_name(CANOEEmission.CO2),
            source,
            capture.factors[technology],
            notes=f"Captured: {notes.capture}",
            units="kt/PJ",
        )
    return entity


def with_om_costs(
    entity: TechnologyEntity,
    technology: Technology,
    costs: pd.DataFrame,
    regions: list[CANOEProvince],
    vintages: list[int],
    notes: GenerationNotes,
):
    """Set the fixed and variable O&M costs of `technology` (a generator or storage)
    that are not NaN"""
    of_costs = costs.loc[costs["technology"] == technology]
    display_name = technology.get_atb_display_name()
    cost_notes = notes.coders_costs if display_name is None else notes.atb_costs
    source_name = display_name or technology.get_coders_generic_type()
    for column, set_cost, units in (
        ("fixed", entity.with_fixed_cost, "M$/GWy"),
        ("variable", entity.with_variable_cost, "M$/PJ"),
    ):
        written = of_costs.dropna(subset=[column])
        if written.empty:
            continue
        set_cost(
            region_vintage_period(written, column, regions, vintages),
            notes=f"{column.capitalize()} O&M ({source_name}): {cost_notes}",
            units=units,
        )


def with_reliability(
    entity: TechnologyEntity,
    technology: GenerationTechnology,
    reliability: Reliability,
    regions: list[CANOEProvince],
    vintages: list[int],
    notes: GenerationNotes,
):
    """Set the capacity credits, reserve capacity derates and ramp rates of
    `technology` that `reliability` has (not those of the bins)"""
    of_credits = reliability.credits.loc[
        reliability.credits["technology"] == technology
    ]
    if not of_credits.empty:
        entity.with_capacity_credit(
            region_vintage_period(of_credits, "credit", regions, vintages),
            notes=notes.capacity_credits,
        )
    of_derates = reliability.derates.loc[
        reliability.derates["technology"] == technology
    ]
    if not of_derates.empty:
        seasons, _ = time_slices()
        derates = RegionVintageSeasonArray(regions, vintages, seasons)
        for region, vintage, factor in zip(
            of_derates["region"], of_derates["vintage"], of_derates["factor"]
        ):
            derates.set_block(
                np.full(len(seasons), float(factor)),
                dims=("season",),
                region=region,
                vintage=int(vintage),
            )
        entity.with_reserve_capacity_derate(derates, notes=notes.reserve_derates)
    of_rates = reliability.ramp_rates.loc[
        reliability.ramp_rates["technology"] == technology, "rate"
    ]
    if not of_rates.empty:
        rates = RegionalValuesArray(regions, fill=float(of_rates.iloc[0]))
        entity.with_ramp_rates(rates, rates, notes=notes.ramp_rates)


def region_vintage(
    df: pd.DataFrame, column: str, regions: list[CANOEProvince], vintages: list[int]
) -> RegionVintageArray:
    """`column` of `df` (columns `region`, `vintage`) as an array"""
    values = RegionVintageArray(regions, vintages)
    for region, vintage, value in zip(df["region"], df["vintage"], df[column]):
        values.set(float(value), region=region, vintage=int(vintage))
    return values


def region_vintage_period(
    df: pd.DataFrame, column: str, regions: list[CANOEProvince], vintages: list[int]
) -> RegionVintagePeriodArray:
    """`column` of `df` (columns `region`, `vintage`, `period`) as an array"""
    periods = sorted({int(p) for p in df["period"]})
    values = RegionVintagePeriodArray(regions, vintages, periods)
    for region, vintage, period, value in zip(
        df["region"], df["vintage"], df["period"], df[column]
    ):
        values.set(
            float(value), region=region, vintage=int(vintage), period=int(period)
        )
    return values


def time_slices() -> tuple[list[str], list[str]]:
    """The seasons (days D001-D365) and times of day (H01-H24) of the model year"""
    hours_per_day, days = 24, 365
    seasons = [hour_to_day(day * hours_per_day) for day in range(days)]
    tods = [hour_to_tod(hour) for hour in range(hours_per_day)]
    return seasons, tods


def _hourly_values(
    factors: pd.DataFrame, regions: list[CANOEProvince]
) -> RegionSeasonTodArray:
    """Hourly `factor` of each region (columns `region`, `hour`) by time slice"""
    seasons, tods = time_slices()
    values = RegionSeasonTodArray(regions, seasons, tods)
    for region, of_region in factors.groupby("region", sort=False):
        hourly = of_region.sort_values("hour")["factor"].to_numpy(dtype=float)
        values.set_block(
            hourly.reshape(len(seasons), len(tods)),
            dims=("season", "tod"),
            region=region,
        )
    return values


def _hourly_vintage_values(
    factors: pd.DataFrame, regions: list[CANOEProvince], vintages: list[int]
) -> RegionVintageSeasonTodArray:
    """Hourly `factor` of each region and vintage (columns `region`, `vintage`,
    `hour`) by time slice"""
    seasons, tods = time_slices()
    values = RegionVintageSeasonTodArray(regions, vintages, seasons, tods)
    for keys, of_process in factors.groupby(["region", "vintage"], sort=False):
        region, vintage = cast(tuple[CANOEProvince, int], keys)
        if region not in regions or vintage not in vintages:
            continue
        hourly = of_process.sort_values("hour")["factor"].to_numpy(dtype=float)
        values.set_block(
            hourly.reshape(len(seasons), len(tods)),
            dims=("season", "tod"),
            region=region,
            vintage=vintage,
        )
    return values


def _daily_values(
    factors: pd.DataFrame, regions: list[CANOEProvince]
) -> RegionSeasonArray:
    """Daily `factor` of each region (columns `region`, `day`) by season (day)"""
    seasons, _ = time_slices()
    values = RegionSeasonArray(regions, seasons)
    for region, of_region in factors.groupby("region", sort=False):
        daily = of_region.sort_values("day")["factor"].to_numpy(dtype=float)
        values.set_block(daily, dims=("season",), region=region)
    return values


def capacity_to_activity() -> float:
    """PJ produced by 1 GW over a year"""
    return 31.536


def _efficiency_notes(
    technology: GenerationTechnology,
    notes: GenerationNotes,
    input_commodity: str | None,
) -> str:
    """Where the efficiency of `technology` comes from"""
    if input_commodity is not None:
        return "Reservoir to electricity, no losses"
    if technology.get_input_fuel() is None:
        return "Free resource, counted as the electricity it generates"
    display_name = technology.get_atb_display_name()
    if display_name is not None:
        return f"1 / heat rate ({display_name}): {notes.atb_efficiency}"
    return (
        "CODERS generation_generic efficiency "
        + f"({technology.get_coders_generic_type()})"
    )

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

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode, OperatorCode, TechnologyTypeCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import (
    FuelCommodityEntity,
    PhysicalCommodityEntity,
    SourceCommodityEntity,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier, get_fuel_commodity_in_sector

from ..catalogue import GenerationTechnology


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
    vre_bin_costs, vre_bin_limits : str
        Source (and currency) of the costs and capacity limits of the wind and
        solar bins.
    """

    capacity: str
    atb_costs: str
    coders_costs: str
    atb_efficiency: str
    cogeneration: str
    vre_bin_costs: str
    vre_bin_limits: str


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


def build_existing_generation(
    fleet: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    efficiencies: pd.DataFrame,
    costs: pd.DataFrame,
    cogeneration: pd.DataFrame,
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
) -> GenerationEntities:
    """
    One `-EXS` technology per technology of the fleet, in the regions and vintages
    where it has capacity; monthly hydro also gets its reservoir inflow (`-IN`).

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
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    # Monthly hydro reservoir: a month of output at full capacity
    RESERVOIR_HOURS = 730

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
        capacity = _region_vintage(of_fleet, "capacity", regions, vintages)

        entity = _generator(
            technology,
            name,
            "existing",
            _region_vintage(
                efficiencies.loc[efficiencies["technology"] == technology],
                "efficiency",
                regions,
                vintages,
            ),
            lifetimes[technology],
            notes,
            data_id,
            input_commodity=reservoir if is_reservoir else None,
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
        _with_om_costs(entity, technology, costs, regions, vintages, notes)

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

        entities.technologies.append(entity)

        if is_reservoir:
            inflow = RegionVintageArray(regions, vintages)
            for record in capacity.to_records():
                inflow.set(1.0, region=record["region"], vintage=record["vintage"])
            entities.technologies.append(
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
                    RegionalValuesArray(regions, fill=_capacity_to_activity()),
                    notes="PJ produced by 1 GW over a year (8760 h)",
                    units="PJ/GWy",
                )
            )

    return entities


def build_new_generation(
    efficiencies: pd.DataFrame,
    investment: pd.DataFrame,
    costs: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
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
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
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
            _region_vintage(of_efficiency, "efficiency", regions, vintages),
            lifetimes[technology],
            notes,
            data_id,
        ).with_investment_cost(
            _region_vintage(
                investment.loc[investment["technology"] == technology],
                "cost",
                regions,
                vintages,
            ),
            notes=f"OCC ({technology.get_atb_display_name()}): {notes.atb_costs}",
            units="M$/GW",
        )
        _with_om_costs(entity, technology, costs, regions, vintages, notes)
        entities.technologies.append(entity)
    return entities


def build_vre_bins(
    investment: pd.DataFrame,
    fixed: pd.DataFrame,
    limits: pd.DataFrame,
    lifetimes: dict[GenerationTechnology, int],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
) -> GenerationEntities:
    """
    One technology per new wind and solar resource bin (`<code>-NEW-<n>`), in the
    regions and vintages of its investment costs, limited to the bin's capacity.

    Parameters
    ----------
    investment, fixed : pd.DataFrame
        See `generation.parameters.vre_bin_costs`.
    limits : pd.DataFrame
        See `generation.parameters.vre_bin_limits`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    technologies: list[GenerationTechnology] = list(
        dict.fromkeys(investment["technology"])
    )
    entities = GenerationEntities(commodities=_commodities(technologies, data_id))
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
                _region_vintage(of_investment, "cost", regions, vintages),
                notes=f"Investment: {notes.vre_bin_costs}",
                units="M$/GW",
            )
            .with_fixed_cost(
                _region_vintage_period(of_fixed, "cost", regions, vintages),
                notes=f"Fixed O&M: {notes.vre_bin_costs}",
                units="M$/GWy",
            )
            .with_limit_capacity(capacity, notes=notes.vre_bin_limits, units="GW")
        )
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
) -> TechnologyEntity:
    """
    A generator from its fuel (or `E_ethos`, or `input_commodity`) to its grid
    level, with its flags, lifetime and capacity to activity.
    """
    fuel = technology.get_input_fuel()
    source = input_commodity or (
        source_commodity_name()
        if fuel is None
        else get_fuel_commodity_in_sector(CANOESector.Electricity, fuel)
    )
    regions: list[CANOEProvince] = list(efficiency.coords["region"])
    return (
        TechnologyEntity(
            name=name,
            output_commodity=technology.get_grid_level().get_commodity(),
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
            RegionalValuesArray(regions, fill=_capacity_to_activity()),
            notes="PJ produced by 1 GW over a year (8760 h)",
            units="PJ/GWy",
        )
    )


def _with_om_costs(
    entity: TechnologyEntity,
    technology: GenerationTechnology,
    costs: pd.DataFrame,
    regions: list[CANOEProvince],
    vintages: list[int],
    notes: GenerationNotes,
):
    """Set the fixed and variable O&M costs of `technology` that are not NaN"""
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
            _region_vintage_period(written, column, regions, vintages),
            notes=f"{column.capitalize()} O&M ({source_name}): {cost_notes}",
            units=units,
        )


def _region_vintage(
    df: pd.DataFrame, column: str, regions: list[CANOEProvince], vintages: list[int]
) -> RegionVintageArray:
    """`column` of `df` (columns `region`, `vintage`) as an array"""
    values = RegionVintageArray(regions, vintages)
    for region, vintage, value in zip(df["region"], df["vintage"], df[column]):
        values.set(float(value), region=region, vintage=int(vintage))
    return values


def _region_vintage_period(
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


def _capacity_to_activity() -> float:
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

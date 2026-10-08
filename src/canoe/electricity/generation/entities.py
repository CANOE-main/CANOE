"""
Temoa objects of the existing generators (`-EXS`), one technology per
`GenerationTechnology` in the fleet:

    E_<fuel> or E_ethos --<TECH>-EXS--> E_elc_tx or E_elc_dx

Monthly hydro is split in two around its reservoir, so the water can be generated
in another season than it arrives in:

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
class ExistingGenerationNotes:
    """
    Notes of the rows of the existing generators.

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
    """

    capacity: str
    atb_costs: str
    coders_costs: str
    atb_efficiency: str
    cogeneration: str


@dataclass
class ExistingGeneration:
    """The commodities and technologies of the existing generators."""

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
    notes: ExistingGenerationNotes,
    data_id: DatasetIdentifier,
) -> ExistingGeneration:
    """
    One `-EXS` technology per technology of the fleet, in the regions and vintages
    where it has capacity; monthly hydro also gets its reservoir inflow (`-IN`).

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.existing_lifetimes`.
    efficiencies : pd.DataFrame
        See `generation.parameters.existing_efficiencies`.
    costs : pd.DataFrame
        See `generation.parameters.existing_om_costs`.
    cogeneration : pd.DataFrame
        See `generation.parameters.cogeneration_activity`.
    notes : ExistingGenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    # Capacity to activity: PJ produced by 1 GW over a year
    CAPACITY_TO_ACTIVITY = 31.536
    # Monthly hydro reservoir: a month of output at full capacity
    RESERVOIR_HOURS = 730

    entities = ExistingGeneration()
    technologies: list[GenerationTechnology] = list(dict.fromkeys(fleet["technology"]))

    # Commodities: the fuels burned, the free resources, the reservoir
    fuels = list(
        dict.fromkeys(
            fuel for t in technologies if (fuel := t.get_input_fuel()) is not None
        )
    )
    for fuel in fuels:
        entities.commodities.append(
            FuelCommodityEntity(
                sector=CANOESector.Electricity,
                fuel=fuel,
                flag=CommodityTypeCode.A,
                data_id=data_id,
            )
        )
    if any(t.get_input_fuel() is None for t in technologies):
        entities.commodities.append(
            SourceCommodityEntity(
                name=source_commodity_name(),
                description="free resources of the generators (water, wind, sun, "
                + "heat)",
                data_id=data_id,
                units="PJ",
            )
        )
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
        rows = fleet["technology"] == technology
        of_technology = fleet.loc[rows]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_technology["region"]))
        vintages = sorted({int(v) for v in of_technology["vintage"]})
        name = f"{technology.get_tech_code()}-EXS"
        fuel = technology.get_input_fuel()
        source = (
            source_commodity_name()
            if fuel is None
            else get_fuel_commodity_in_sector(CANOESector.Electricity, fuel)
        )
        is_reservoir = technology == GenerationTechnology.HydroMonthly

        capacity = RegionVintageArray(regions, vintages)
        for region, vintage, value in zip(
            of_technology["region"], of_technology["vintage"], of_technology["capacity"]
        ):
            capacity.set(float(value), region=region, vintage=int(vintage))
        efficiency = RegionVintageArray(regions, vintages)
        of_efficiency = efficiencies.loc[efficiencies["technology"] == technology]
        for region, vintage, value in zip(
            of_efficiency["region"],
            of_efficiency["vintage"],
            of_efficiency["efficiency"],
        ):
            efficiency.set(float(value), region=region, vintage=int(vintage))

        generic_type = technology.get_coders_generic_type()
        lifetime_notes = (
            "Never retires: kept for the whole horizon"
            if technology.never_retires()
            else f"CODERS generation_generic service_life ({generic_type})"
        )
        capacity_notes = notes.capacity + (
            "; never retires, so all units are in the last existing vintage"
            if technology.never_retires()
            else ""
        )

        entity = (
            TechnologyEntity(
                name=name,
                output_commodity=technology.get_grid_level().get_commodity(),
                data_id=data_id,
                description=f"{technology.get_description()} - existing",
                sector=CANOESector.Electricity,
                flag=TechnologyTypeCode.PS
                if is_reservoir
                else TechnologyTypeCode.PB
                if technology.is_baseload()
                else TechnologyTypeCode.P,
            )
            .set_reserve()
            .set_curtailable(technology.is_curtailable())
            .with_efficiency(
                reservoir if is_reservoir else source,
                efficiency,
                notes=_efficiency_notes(technology, notes),
                units="PJ/PJ",
            )
            .with_existing_capacity(capacity, notes=capacity_notes, units="GW")
            .with_lifetime(
                RegionalValuesArray(regions, fill=lifetimes[technology]),
                notes=lifetime_notes,
            )
            .with_capacity_to_activity(
                RegionalValuesArray(regions, fill=CAPACITY_TO_ACTIVITY),
                notes="PJ produced by 1 GW over a year (8760 h)",
                units="PJ/GWy",
            )
        )
        if is_reservoir:
            entity.set_seasonal_storage().with_storage_duration(
                RegionalValuesArray(regions, fill=RESERVOIR_HOURS),
                notes="Hours of output at full capacity: about a month",
            )

        # Operation and maintenance costs
        of_costs = costs.loc[costs["technology"] == technology]
        periods = sorted({int(p) for p in of_costs["period"]})
        cost_notes = (
            notes.coders_costs
            if technology.get_atb_display_name() is None
            else notes.atb_costs
        )
        source_name = technology.get_atb_display_name() or generic_type
        for column, set_cost, units in (
            ("fixed", entity.with_fixed_cost, "M$/GWy"),
            ("variable", entity.with_variable_cost, "M$/PJ"),
        ):
            values = RegionVintagePeriodArray(regions, vintages, periods)
            written = of_costs.dropna(subset=[column])
            for region, vintage, period, value in zip(
                written["region"],
                written["vintage"],
                written["period"],
                written[column],
            ):
                values.set(
                    float(value),
                    region=region,
                    vintage=int(vintage),
                    period=int(period),
                )
            if not written.empty:
                set_cost(
                    values,
                    notes=f"{column.capitalize()} O&M ({source_name}): {cost_notes}",
                    units=units,
                )

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
                    source,
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
                    RegionalValuesArray(regions, fill=CAPACITY_TO_ACTIVITY),
                    notes="PJ produced by 1 GW over a year (8760 h)",
                    units="PJ/GWy",
                )
            )

    return entities


def _efficiency_notes(
    technology: GenerationTechnology, notes: ExistingGenerationNotes
) -> str:
    """Where the efficiency of `technology` comes from"""
    if technology == GenerationTechnology.HydroMonthly:
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

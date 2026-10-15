"""
Temoa objects of the storage: existing (`-EXS`) and new (`-NEW`), one technology per
`StorageTechnology`, on the transmission level:

    E_elc_tx --<TECH>-EXS/-NEW--> E_elc_tx

Storage technologies (flag `ps`) take electricity in and give it back later, losing
the round trip; their duration is the hours of output at full power from full
storage.
"""

import pandas as pd
from canoe_schema.v4_0 import TechnologyTypeCode

from canoe.canoe_objects.array_types import RegionalValuesArray, RegionVintageArray
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier

from ..catalogue import GridLevel, StorageTechnology
from ..generation.entities import (
    GenerationNotes,
    capacity_to_activity,
    region_vintage,
    with_om_costs,
)


def build_existing_storage(
    fleet: pd.DataFrame,
    efficiencies: pd.DataFrame,
    costs: pd.DataFrame,
    lifetimes: dict[StorageTechnology, int],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
) -> list[TechnologyEntity]:
    """
    One `-EXS` technology per storage technology of the fleet, in the regions and
    vintages where it has capacity.

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_storage`.
    efficiencies : pd.DataFrame
        See `storage.parameters.storage_efficiencies`.
    costs : pd.DataFrame
        See `generation.parameters.process_om_costs`.
    lifetimes : dict[StorageTechnology, int]
        See `storage.parameters.storage_lifetimes`.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    technologies: list[StorageTechnology] = list(dict.fromkeys(fleet["technology"]))
    entities: list[TechnologyEntity] = []
    for technology in technologies:
        of_fleet = fleet.loc[fleet["technology"] == technology]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_fleet["region"]))
        vintages = sorted({int(v) for v in of_fleet["vintage"]})
        entity = _storage(
            technology,
            "existing",
            region_vintage(
                efficiencies.loc[efficiencies["technology"] == technology],
                "efficiency",
                regions,
                vintages,
            ),
            lifetimes[technology],
            data_id,
        ).with_existing_capacity(
            region_vintage(of_fleet, "capacity", regions, vintages),
            notes=notes.capacity
            + (
                "; never retires, so all units are in the last existing vintage"
                if technology.never_retires()
                else ""
            ),
            units="GW",
        )
        with_om_costs(entity, technology, costs, regions, vintages, notes)
        entities.append(entity)
    return entities


def build_new_storage(
    efficiencies: pd.DataFrame,
    investment: pd.DataFrame,
    costs: pd.DataFrame,
    lifetimes: dict[StorageTechnology, int],
    notes: GenerationNotes,
    data_id: DatasetIdentifier,
) -> list[TechnologyEntity]:
    """
    One `-NEW` technology per new storage technology, in the regions and vintages of
    `efficiencies`.

    Parameters
    ----------
    efficiencies : pd.DataFrame
        See `storage.parameters.storage_efficiencies` (of
        `generation.parameters.new_processes`).
    investment : pd.DataFrame
        See `generation.parameters.process_investment_costs`.
    costs : pd.DataFrame
        See `generation.parameters.process_om_costs`.
    lifetimes : dict[StorageTechnology, int]
        See `storage.parameters.storage_lifetimes`.
    notes : GenerationNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    technologies: list[StorageTechnology] = list(
        dict.fromkeys(efficiencies["technology"])
    )
    entities: list[TechnologyEntity] = []
    for technology in technologies:
        of_efficiency = efficiencies.loc[efficiencies["technology"] == technology]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_efficiency["region"]))
        vintages = sorted({int(v) for v in of_efficiency["vintage"]})
        entity = _storage(
            technology,
            "new",
            region_vintage(of_efficiency, "efficiency", regions, vintages),
            lifetimes[technology],
            data_id,
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
        entities.append(entity)
    return entities


def _storage(
    technology: StorageTechnology,
    kind: str,
    efficiency: RegionVintageArray,
    lifetime: int,
    data_id: DatasetIdentifier,
) -> TechnologyEntity:
    """A storage technology on the transmission level, with its round-trip
    efficiency, duration, lifetime and capacity to activity."""
    grid = GridLevel.Transmission.get_commodity()
    regions: list[CANOEProvince] = list(efficiency.coords["region"])
    return (
        TechnologyEntity(
            name=f"{technology.get_tech_code()}-{'EXS' if kind == 'existing' else 'NEW'}",
            output_commodity=grid,
            data_id=data_id,
            description=f"{technology.get_description()} - {kind}",
            sector=CANOESector.Electricity,
            flag=TechnologyTypeCode.PS,
        )
        .set_reserve()
        .with_efficiency(
            grid,
            efficiency,
            notes="Round trip, electricity out per unit stored (default from NREL "
            + "ATB)",
            units="PJ/PJ",
        )
        .with_storage_duration(
            RegionalValuesArray(regions, fill=technology.get_duration_hours()),
            notes="Hours of output at full power from full storage",
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

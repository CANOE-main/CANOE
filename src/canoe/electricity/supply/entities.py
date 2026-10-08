"""
Temoa objects of the grid and of the delivery to the sectors:

    E_elc_tx --E_ELC_TX_to_DX--> E_elc_dx --E_ELC_DX_to_DEM--> E_elc_dem --E_<S>_ELC--> <S>_elc

All are pass-throughs with unlimited capacity and a single vintage, the first model
period, whose lifetime reaches the end of the horizon (see
`canoe.common.periods.horizon_length`).
"""

from dataclasses import dataclass, field
from sqlite3 import Connection

import pandas as pd

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import PhysicalCommodityEntity
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier, get_fuel_commodity_in_sector

from ..catalogue import GridLevel


def delivery_technology_name(sector: CANOESector) -> str:
    """
    Technology delivering electricity to `sector`.

    Examples
    --------
    >>> delivery_technology_name(CANOESector.Industry)
    'E_I_ELC'
    """
    return f"E_{sector.get_tag()}_ELC"


@dataclass
class GridEntities:
    """The grid commodities and technologies, and the delivery technologies."""

    commodities: list[PhysicalCommodityEntity] = field(default_factory=list)
    grid: list[TechnologyEntity] = field(default_factory=list)
    deliveries: list[TechnologyEntity] = field(default_factory=list)

    def build(self, db_conn: Connection):
        """Write the commodities first, then the technologies that use them."""
        for commodity in self.commodities:
            commodity.build(db_conn)
        for technology in self.grid + self.deliveries:
            technology.build(db_conn)


def build_grid(
    efficiencies: pd.DataFrame,
    costs: pd.DataFrame,
    electricity_imports: list[CANOEFuelImport],
    first_period: int,
    lifetime: int,
    cost_notes: str,
    data_id: DatasetIdentifier,
) -> GridEntities:
    """
    The grid of every province in `efficiencies`, and the delivery to each sector
    in the provinces where it imports electricity.

    Parameters
    ----------
    efficiencies : pd.DataFrame
        Transmission to distribution efficiency, columns `region` and `efficiency`,
        see `parameters.transmission_efficiencies`.
    costs : pd.DataFrame
        Variable cost (M$/PJ) of each grid level, columns `level`, `period` and
        `cost`, see `parameters.grid_variable_costs`.
    electricity_imports : list[CANOEFuelImport]
        One per sector, see `build.electricity_imports`.
    first_period : int
        The single vintage of every technology.
    lifetime : int
        Their lifetime, see `canoe.common.periods.horizon_length`.
    cost_notes : str
        Notes of the cost rows (source, projection year, currency).
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    regions: list[CANOEProvince] = list(efficiencies["region"])
    demand_commodity = "E_elc_dem"  # electricity ready for the sectors
    entities = GridEntities()
    descriptions = {
        GridLevel.Transmission.get_commodity(): "electricity on the transmission grid",
        GridLevel.Distribution.get_commodity(): "electricity on the distribution grid",
        demand_commodity: "electricity delivered to the sectors",
    }
    for name, description in descriptions.items():
        entities.commodities.append(
            PhysicalCommodityEntity(name=name, description=description, data_id=data_id)
        )

    transmission = RegionVintageArray(regions, [first_period])
    for region, efficiency in zip(efficiencies["region"], efficiencies["efficiency"]):
        transmission.set(float(efficiency), region=region, vintage=first_period)
    entities.grid.append(
        _pass_through(
            name="E_ELC_TX_to_DX",
            input_commodity=GridLevel.Transmission.get_commodity(),
            output_commodity=GridLevel.Distribution.get_commodity(),
            description="transmission-side electricity to distribution-side "
            + "electricity",
            sector=CANOESector.Electricity,
            efficiencies=transmission,
            efficiency_notes="1 - CODERS system line losses (transmission and "
            + "distribution), CA_system_parameters system_line_losses_percent",
            lifetime=lifetime,
            data_id=data_id,
        ).with_variable_cost(
            _level_costs(costs, GridLevel.Transmission, regions, first_period),
            notes=f"Transmission cost: {cost_notes}",
            units="M$/PJ",
        )
    )
    entities.grid.append(
        _pass_through(
            name="E_ELC_DX_to_DEM",
            input_commodity=GridLevel.Distribution.get_commodity(),
            output_commodity=demand_commodity,
            description="distribution-side electricity to demand-side electricity",
            sector=CANOESector.Electricity,
            efficiencies=RegionVintageArray(regions, [first_period], fill=1.0),
            efficiency_notes="No losses: the system line losses are taken from "
            + "transmission to distribution",
            lifetime=lifetime,
            data_id=data_id,
        ).with_variable_cost(
            _level_costs(costs, GridLevel.Distribution, regions, first_period),
            notes=f"Distribution cost: {cost_notes}",
            units="M$/PJ",
        )
    )

    for electricity_import in electricity_imports:
        sector = electricity_import.sector
        entities.deliveries.append(
            _pass_through(
                name=delivery_technology_name(sector),
                input_commodity=demand_commodity,
                output_commodity=get_fuel_commodity_in_sector(
                    sector, CANOEFuel.Electricity
                ),
                description=f"electricity delivery to the {str(sector).lower()} "
                + "sector",
                sector=sector,
                efficiencies=RegionVintageArray(
                    list(electricity_import.provinces), [first_period], fill=1.0
                ),
                efficiency_notes="Delivery to the sector, efficiency 1",
                lifetime=lifetime,
                data_id=data_id,
            )
        )
    return entities


def _pass_through(
    name: str,
    input_commodity: str,
    output_commodity: str,
    description: str,
    sector: CANOESector,
    efficiencies: RegionVintageArray,
    efficiency_notes: str,
    lifetime: int,
    data_id: DatasetIdentifier,
) -> TechnologyEntity:
    """A technology with unlimited capacity from `input_commodity` to
    `output_commodity`, in the regions and vintage of `efficiencies`."""
    regions: list[CANOEProvince] = list(efficiencies.coords["region"])
    return (
        TechnologyEntity(
            name=name,
            output_commodity=output_commodity,
            data_id=data_id,
            description=description,
            sector=sector,
        )
        .set_unlimited_capacity()
        .with_efficiency(
            input_commodity, efficiencies, notes=efficiency_notes, units="PJ/PJ"
        )
        .with_lifetime(
            RegionalValuesArray(regions, fill=lifetime),
            notes="From the first model period to the end of the horizon, so the "
            + "single vintage serves every period",
        )
    )


def _level_costs(
    costs: pd.DataFrame,
    level: GridLevel,
    regions: list[CANOEProvince],
    vintage: int,
) -> RegionVintagePeriodArray:
    """The cost of `level` in each period, the same in every region"""
    of_level = costs[costs["level"].isin([level])]
    periods = [int(p) for p in of_level["period"]]
    array = RegionVintagePeriodArray(regions, [vintage], periods)
    for period, cost in zip(periods, of_level["cost"]):
        for region in regions:
            array.set(float(cost), region=region, vintage=vintage, period=period)
    return array

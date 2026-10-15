"""
Temoa objects of the trade of electricity, on the transmission grid:

    E_elc_tx(r1) --E_INT (exchange, r1-r2)--> E_elc_tx(r2)
    E_elc_tx --E_INT_OUT-<OUT>--> E_D_elc_int_<out>   (exports, a fixed demand)
    E_ethos --E_INT_IN-<OUT>--> E_elc_tx               (imports, a fixed generator)

`<OUT>` is the region outside the model: `USA`, or a province left out. All have a
single vintage, the year before the first period, and never retire (see
`common.periods.never_retiring_lifetime`).
"""

from dataclasses import dataclass, field
from sqlite3 import Connection
from typing import cast

import pandas as pd

from canoe.canoe_objects.array_types import (
    PairPeriodArray,
    PairSeasonTodArray,
    PairValuesArray,
    RegionalValuesArray,
    RegionPair,
    RegionSeasonTodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import SourceCommodityEntity
from canoe.canoe_objects.demand import (
    DemandEntity,
    DemandSeriesArray,
    DemandSpecificDistributionArray,
)
from canoe.canoe_objects.exchange import ExchangeTechnologyEntity
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier

from ..catalogue import GridLevel
from ..generation.entities import (
    capacity_to_activity,
    source_commodity_name,
    time_slices,
)


@dataclass(frozen=True)
class TradeNotes:
    """
    Notes of the trade rows.

    Parameters
    ----------
    losses : str
        Source of the losses on the interties and exports.
    capacities, flows : str
        Source of the intertie capacities and of the historical flows.
    costs : str
        Source of the transmission cost.
    """

    losses: str
    capacities: str
    flows: str
    costs: str


@dataclass
class BoundaryEntities:
    """The exports (demands and their technologies) and imports of the boundary
    interties."""

    commodities: list[SourceCommodityEntity] = field(default_factory=list)
    demands: list[DemandEntity] = field(default_factory=list)
    technologies: list[TechnologyEntity] = field(default_factory=list)

    def build(self, db_conn: Connection):
        """Write the commodities and demands first, then the technologies."""
        for commodity in self.commodities:
            commodity.build(db_conn)
        for demand in self.demands:
            demand.build(db_conn)
        for technology in self.technologies:
            technology.build(db_conn)


def build_interties(
    interties: pd.DataFrame,
    capacities: pd.DataFrame,
    capacity_factors: pd.DataFrame,
    losses: dict[CANOEProvince, float],
    costs: pd.DataFrame,
    vintage: int,
    lifetime: int,
    notes: TradeNotes,
    data_id: DatasetIdentifier,
) -> ExchangeTechnologyEntity:
    """
    `E_INT`, the interties between modelled provinces, in both directions of each
    pair.

    Parameters
    ----------
    interties : pd.DataFrame
        See `trade.parameters.endogenous_interties`.
    capacities : pd.DataFrame
        See `trade.parameters.intertie_capacities`.
    capacity_factors : pd.DataFrame
        See `trade.parameters.intertie_capacity_factors`.
    losses : dict[CANOEProvince, float]
        Losses of the sending province, see `trade.parameters.intertie_losses`.
    costs : pd.DataFrame
        Variable cost of each grid level, see `supply.parameters.grid_variable_costs`;
        the interties take the transmission cost.
    vintage, lifetime : int
        The single vintage and its lifetime.
    notes : TradeNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    pairs: list[RegionPair] = list(
        zip(interties["from_region"], interties["to_region"])
    )
    efficiency = PairValuesArray(pairs)
    for pair in pairs:
        efficiency.set(1.0 - losses[pair[0]], pair=pair)
    capacity = PairValuesArray(pairs)
    for f, t, value in zip(
        capacities["from_region"], capacities["to_region"], capacities["capacity"]
    ):
        capacity.set(float(value), pair=(f, t))
    transmission = _transmission_costs(costs)
    variable = PairPeriodArray(pairs, list(transmission))
    for period, cost in transmission.items():
        for pair in pairs:
            variable.set(cost, pair=pair, period=period)

    entity = (
        ExchangeTechnologyEntity(
            name="E_INT",
            commodity=GridLevel.Transmission.get_commodity(),
            vintage=vintage,
            data_id=data_id,
            description="endogenous inter-regional intertie",
            sector=CANOESector.Electricity,
        )
        .with_efficiency(
            efficiency,
            notes=f"1 - losses of the sending province: {notes.losses}",
            units="PJ/PJ",
        )
        .with_existing_capacity(
            capacity,
            notes="Largest transfer capability of the pair, in either season and "
            + f"direction: {notes.capacities}",
            units="GW",
        )
        .with_lifetime(
            PairValuesArray(pairs, fill=lifetime),
            notes="Never retires: kept for the whole horizon",
        )
        .with_capacity_to_activity(
            PairValuesArray(pairs, fill=capacity_to_activity()),
            notes="PJ carried by 1 GW over a year (8760 h)",
            units="PJ/GWy",
        )
        .with_variable_cost(
            variable, notes=f"Transmission cost: {notes.costs}", units="M$/PJ"
        )
    )
    if not capacity_factors.empty:
        seasons, tods = time_slices()
        factors = PairSeasonTodArray(pairs, seasons, tods)
        for keys, of_pair in capacity_factors.groupby(
            ["from_region", "to_region"], sort=False
        ):
            hourly = of_pair.sort_values("hour")["factor"].to_numpy(dtype=float)
            factors.set_block(
                hourly.reshape(len(seasons), len(tods)),
                dims=("season", "tod"),
                pair=cast(RegionPair, keys),
            )
        entity.with_capacity_factor(
            factors,
            notes="Transfer capability of the direction in the season (summer May to "
            + f"October) over the capacity: {notes.capacities}",
        )
    return entity


def build_boundary(
    demands: pd.DataFrame,
    profiles: pd.DataFrame,
    import_capacities: pd.DataFrame,
    import_factors: pd.DataFrame,
    losses: dict[CANOEProvince, float],
    costs: pd.DataFrame,
    vintage: int,
    lifetime: int,
    notes: TradeNotes,
    data_id: DatasetIdentifier,
) -> BoundaryEntities:
    """
    The boundary interties of each outside region: exports (`E_INT_OUT-<OUT>`, an
    annual pass-through to the demand `E_D_elc_int_<out>`, which follows the
    historical outflow) and imports (`E_INT_IN-<OUT>`, a curtailable generator whose
    capacity factor follows the historical inflow).

    Parameters
    ----------
    demands, profiles : pd.DataFrame
        See `trade.parameters.export_demands` and `export_profiles`.
    import_capacities, import_factors : pd.DataFrame
        See `trade.parameters.import_capacities` and `import_capacity_factors`.
    losses : dict[CANOEProvince, float]
        Losses of the exporting province, see `trade.parameters.intertie_losses`.
    costs : pd.DataFrame
        Variable cost of each grid level; exports take the transmission cost.
    vintage, lifetime : int
        The single vintage and its lifetime.
    notes : TradeNotes
        Notes of the rows.
    data_id : DatasetIdentifier
        Data set of the electricity module.
    """
    grid = GridLevel.Transmission.get_commodity()
    seasons, tods = time_slices()
    transmission = _transmission_costs(costs)
    periods = sorted({int(p) for p in demands["period"]})
    entities = BoundaryEntities()

    for outside in dict.fromkeys(demands["outside"]):
        of_demand = demands.loc[demands["outside"] == outside]
        regions: list[CANOEProvince] = list(dict.fromkeys(of_demand["region"]))
        commodity = f"E_D_elc_int_{outside.lower()}"
        series = DemandSeriesArray(regions, periods)
        for region, period, value in zip(
            of_demand["region"], of_demand["period"], of_demand["demand"]
        ):
            series.set(float(value), region=region, period=int(period))
        distribution = DemandSpecificDistributionArray(regions, periods, seasons, tods)
        of_profile = profiles.loc[profiles["outside"] == outside]
        for region, of_region in of_profile.groupby("region", sort=False):
            hourly = of_region.sort_values("hour")["share"].to_numpy(dtype=float)
            for period in periods:
                distribution.set_block(
                    hourly.reshape(len(seasons), len(tods)),
                    dims=("season", "tod"),
                    region=region,
                    period=period,
                )
        entities.demands.append(
            DemandEntity(
                name=commodity,
                commodity_description=f"electricity leaving the model to {outside}",
                unit="PJ",
                data_id=data_id,
            )
            .with_demand_series(
                series,
                notes=f"Historical outflow to {outside}, every period: {notes.flows}",
            )
            .with_dsd(distribution, notes=f"Hourly share of the outflow: {notes.flows}")
        )

        efficiency = RegionVintageArray(regions, [vintage])
        for region in regions:
            efficiency.set(1.0 - losses[region], region=region, vintage=vintage)
        variable = RegionVintagePeriodArray(regions, [vintage], list(transmission))
        for period, cost in transmission.items():
            for region in regions:
                variable.set(cost, region=region, vintage=vintage, period=period)
        entities.technologies.append(
            TechnologyEntity(
                name=f"E_INT_OUT-{outside}",
                output_commodity=commodity,
                data_id=data_id,
                description=f"boundary intertie leaving the model to {outside}, "
                + "treated as a demand",
                sector=CANOESector.Electricity,
            )
            .set_annual()
            .set_unlimited_capacity()
            .with_efficiency(
                grid,
                efficiency,
                notes=f"1 - losses of the exporting province: {notes.losses}",
                units="PJ/PJ",
            )
            .with_lifetime(
                RegionalValuesArray(regions, fill=lifetime),
                notes="Never retires: kept for the whole horizon",
            )
            .with_capacity_to_activity(
                RegionalValuesArray(regions, fill=capacity_to_activity()),
                notes="PJ carried by 1 GW over a year (8760 h)",
                units="PJ/GWy",
            )
            .with_variable_cost(
                variable, notes=f"Transmission cost: {notes.costs}", units="M$/PJ"
            )
        )

    for outside in dict.fromkeys(import_capacities["outside"]):
        of_capacity = import_capacities.loc[import_capacities["outside"] == outside]
        regions = list(dict.fromkeys(of_capacity["region"]))
        capacity = RegionVintageArray(regions, [vintage])
        for region, value in zip(of_capacity["region"], of_capacity["capacity"]):
            capacity.set(float(value), region=region, vintage=vintage)
        factors = RegionSeasonTodArray(regions, seasons, tods)
        of_factors = import_factors.loc[import_factors["outside"] == outside]
        for region, of_region in of_factors.groupby("region", sort=False):
            hourly = of_region.sort_values("hour")["factor"].to_numpy(dtype=float)
            factors.set_block(
                hourly.reshape(len(seasons), len(tods)),
                dims=("season", "tod"),
                region=region,
            )
        entities.technologies.append(
            TechnologyEntity(
                name=f"E_INT_IN-{outside}",
                output_commodity=grid,
                data_id=data_id,
                description=f"boundary intertie entering the model from {outside}, "
                + "treated as a variable generator",
                sector=CANOESector.Electricity,
            )
            .set_curtailable()
            .with_efficiency(
                source_commodity_name(),
                RegionVintageArray(regions, [vintage], fill=1.0),
                notes="The electricity entering, counted at the border",
                units="PJ/PJ",
            )
            .with_existing_capacity(
                capacity,
                notes=f"Largest historical hourly inflow from {outside}: {notes.flows}",
                units="GW",
            )
            .with_lifetime(
                RegionalValuesArray(regions, fill=lifetime),
                notes="Never retires: kept for the whole horizon",
            )
            .with_capacity_to_activity(
                RegionalValuesArray(regions, fill=capacity_to_activity()),
                notes="PJ carried by 1 GW over a year (8760 h)",
                units="PJ/GWy",
            )
            .with_capacity_factor(
                factors,
                notes=f"Historical hourly inflow over the largest: {notes.flows}",
            )
        )
    if not import_capacities.empty:
        entities.commodities.append(
            SourceCommodityEntity(
                name=source_commodity_name(),
                description="free resources of the generators (water, wind, sun, "
                + "heat)",
                data_id=data_id,
                units="PJ",
            )
        )
    return entities


def _transmission_costs(costs: pd.DataFrame) -> dict[int, float]:
    """Transmission cost (M$/PJ) of each period"""
    of_level = costs.loc[costs["level"] == GridLevel.Transmission]
    return {int(p): float(c) for p, c in zip(of_level["period"], of_level["cost"])}

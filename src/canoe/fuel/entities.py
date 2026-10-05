"""
Temoa objects of the fuel supply: the commodities and technologies that bring each
fuel from the `F_ethos` source to the sectors that consume it.

```
F_ethos ──F_IMP_NG──▶ F_ng ──F_C_NG──▶ C_ng   (built by the commercial sector)
 source    import      fuel ──F_A_NG──▶ A_ng   (built by the agriculture sector)
                              distribution
```

Takes the parameters computed in `build.py` (tidy frames, see `build_fuel_supply`)
and turns them into `canoe_objects` entities. Nothing in here touches the database
until `FuelSupplyEntities.build`. The sector fuel commodities (`C_ng`, ...) belong to
the sectors and must already exist.

Every technology is a transfer: efficiency 1, unlimited capacity, annual, with a
lifetime of one period so each vintage only supplies its own period. The variable
costs are the fuel prices, the emission activities the fuel's emissions:

- `F_IMP_<FUEL>` (sector `fuel`): the import cost, and the upstream emissions of
  producing and delivering the fuel.
- `F_<S>_<FUEL>` (the consuming sector, so its emissions show in that sector): the
  distribution cost, and the combustion emissions of the fuel in that sector.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from sqlite3 import Connection

import pandas as pd
from canoe_schema.v4_0 import CommodityTypeCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.commodity import FuelCommodityEntity, SourceCommodityEntity
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import (
    CANOEEmission,
    CANOEEmissionDeclaration,
    CANOEFuel,
    CANOEProvince,
    CANOESector,
    DataQualityProfile,
)
from canoe.common.naming import (
    DatasetIdentifier,
    get_emission_commodity_name,
    get_fuel_commodity_in_sector,
)

SOURCE_COMMODITY = "F_ethos"
"""Source commodity of every fuel import."""

COST_UNITS = "M$/PJ"
EMISSION_UNITS = "kt/PJ"

_COST_DATA_QUALITY = DataQualityProfile(cred=2, geog=3, struc=2, tech=1, time=1)
_EMISSION_DATA_QUALITY = DataQualityProfile(cred=1, geog=2, struc=2, tech=2, time=2)


def fuel_commodity_name(fuel: CANOEFuel) -> str:
    """
    Commodity of a fuel in the fuel sector, between its import and distribution.

    Examples
    --------
    >>> fuel_commodity_name(CANOEFuel.NaturalGas)
    'F_ng'
    """
    return get_fuel_commodity_in_sector(CANOESector.Fuel, fuel)


def import_technology_name(fuel: CANOEFuel) -> str:
    """
    Examples
    --------
    >>> import_technology_name(CANOEFuel.NaturalGas)
    'F_IMP_NG'
    """
    return f"{CANOESector.Fuel.get_tag()}_IMP_{fuel.value}"


def distribution_technology_name(sector: CANOESector, fuel: CANOEFuel) -> str:
    """
    Examples
    --------
    >>> distribution_technology_name(CANOESector.Commercial, CANOEFuel.NaturalGas)
    'F_C_NG'
    """
    return f"{CANOESector.Fuel.get_tag()}_{sector.get_tag()}_{fuel.value}"


@dataclass
class FuelSupplyEntities:
    """
    Everything the fuel supply writes, in build order: the source commodity, the fuel
    commodities, the imports and the distribution technologies.

    `emissions` are the gases written, to declare in the module output: upstream
    emissions under the fuel sector, combustion emissions under each consuming
    sector.
    """

    source: SourceCommodityEntity
    fuel_commodities: list[FuelCommodityEntity] = field(default_factory=list)
    imports: list[TechnologyEntity] = field(default_factory=list)
    distributions: list[TechnologyEntity] = field(default_factory=list)
    emissions: list[CANOEEmissionDeclaration] = field(default_factory=list)

    def build(self, db_conn: Connection):
        """
        Write all the entities, commodities first. The sector fuel commodities the
        distribution technologies output must already exist. Nothing is written if
        there are no imports.

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        if not self.imports:
            return
        self.source.build(db_conn)
        for commodity in self.fuel_commodities:
            commodity.build(db_conn)
        for technology in [*self.imports, *self.distributions]:
            technology.build(db_conn)


def build_fuel_supply(
    import_costs: pd.DataFrame,
    distribution_costs: pd.DataFrame,
    upstream_factors: pd.DataFrame,
    combustion_factors: pd.DataFrame,
    lifetime: float,
    data_id: DatasetIdentifier,
) -> FuelSupplyEntities:
    """
    The fuel supply entities: an import technology per fuel in `import_costs` and a
    distribution technology per (sector, fuel) in `distribution_costs`.

    A technology exists in the (region, period) where it has a cost row: its
    efficiency, variable cost and emission activities are written there, with the
    period as vintage. Emission factors apply to every row of their fuel (and sector,
    for combustion); fuels without factors emit nothing.

    params:
    - import_costs: one row per (region, period, fuel) supplied, with columns `region`
      (`CANOEProvince`), `period`, `fuel` (`CANOEFuel`), `cost` (M$/PJ) and `notes`
      (the notes of the first row of each fuel are written). Not modified.
    - distribution_costs: one row per (region, period, sector, fuel) supplied, with
      the columns of `import_costs` plus `sector` (`CANOESector`, the consuming
      sector). Every fuel must have import costs in the same (region, period).
    - upstream_factors: emissions of producing and delivering each fuel, one row per
      (fuel, emission) with columns `fuel`, `emission` (`CANOEEmission`), `factor`
      (kt per PJ of fuel), `notes` and `reference`, see
      `canoe.fuel.loaders.get_upstream_emission_factors`.
    - combustion_factors: emissions of burning each fuel in each sector, the columns
      of `upstream_factors` plus `sector`, see
      `canoe.fuel.loaders.get_combustion_emission_factors`.
    - lifetime: technology lifetime (years), one period so each vintage only
      supplies its own period

    Raises
    ------
    ValueError
        If a technology has more than one cost row per (region, period), or a
        distribution technology has no import in some (region, period).
    """
    supply = FuelSupplyEntities(
        source=SourceCommodityEntity(
            name=SOURCE_COMMODITY,
            description="supply point of the fuels imported into the fuel sector",
            data_id=data_id,
            units="PJ",
        )
    )
    emissions: set[tuple[CANOESector, CANOEEmission]] = set()

    # NOTE: enum columns are filtered with `isin`: with pandas 3 `str` columns,
    # `== CANOEFuel.X` compares against str(CANOEFuel.X) (the name), never matching
    for fuel in _unique(import_costs["fuel"]):
        costs = import_costs.loc[import_costs["fuel"].isin([fuel])]
        factors = upstream_factors.loc[upstream_factors["fuel"].isin([fuel])]
        supply.fuel_commodities.append(
            FuelCommodityEntity(
                sector=CANOESector.Fuel,
                fuel=fuel,
                flag=CommodityTypeCode.P,
                data_id=data_id,
            )
        )
        technology = _transfer_technology(
            name=import_technology_name(fuel),
            input_commodity=SOURCE_COMMODITY,
            output_commodity=fuel_commodity_name(fuel),
            description=f"{fuel.get_desc_name()} import into the fuel sector",
            sector=CANOESector.Fuel,
            costs=costs,
            lifetime=lifetime,
            data_id=data_id,
        )
        _add_emission_factors(technology, SOURCE_COMMODITY, factors)
        emissions |= {(CANOESector.Fuel, e) for e in factors["emission"]}
        supply.imports.append(technology)

    imported = set(
        zip(import_costs["region"], import_costs["period"], import_costs["fuel"])
    )
    pairs = _unique(zip(distribution_costs["sector"], distribution_costs["fuel"]))
    for sector, fuel in pairs:
        costs = distribution_costs.loc[
            distribution_costs["sector"].isin([sector])
            & distribution_costs["fuel"].isin([fuel])
        ]
        not_imported = [
            (region, period)
            for region, period in zip(costs["region"], costs["period"])
            if (region, period, fuel) not in imported
        ]
        if not_imported:
            raise ValueError(
                f"{distribution_technology_name(sector, fuel)}: no import of "
                + f"{fuel.get_desc_name()} at {not_imported}"
            )
        factors = combustion_factors.loc[
            combustion_factors["sector"].isin([sector])
            & combustion_factors["fuel"].isin([fuel])
        ]
        technology = _transfer_technology(
            name=distribution_technology_name(sector, fuel),
            input_commodity=fuel_commodity_name(fuel),
            output_commodity=get_fuel_commodity_in_sector(sector, fuel),
            description=f"{fuel.get_desc_name()} distribution to the "
            + f"{str(sector).lower()} sector",
            sector=sector,
            costs=costs,
            lifetime=lifetime,
            data_id=data_id,
        )
        _add_emission_factors(technology, fuel_commodity_name(fuel), factors)
        emissions |= {(sector, e) for e in factors["emission"]}
        supply.distributions.append(technology)

    supply.emissions = [
        CANOEEmissionDeclaration(sector=sector, emission=emission)
        for sector, emission in sorted(emissions, key=str)
    ]
    return supply


def _transfer_technology(
    name: str,
    input_commodity: str,
    output_commodity: str,
    description: str,
    sector: CANOESector,
    costs: pd.DataFrame,
    lifetime: float,
    data_id: DatasetIdentifier,
) -> TechnologyEntity:
    """
    A technology passing `input_commodity` to `output_commodity` with efficiency 1,
    in the (region, period) of `costs` (columns `region`, `period`, `cost`, `notes`),
    at that variable cost with the period as vintage.
    """
    if costs.duplicated(["region", "period"]).any():
        raise ValueError(f"{name}: more than one cost per (region, period)")
    regions: list[CANOEProvince] = _unique(costs["region"])
    periods: list[int] = sorted(_unique(costs["period"]))

    efficiency = RegionVintageArray(regions, periods)
    variable_cost = RegionVintagePeriodArray(regions, periods, periods)
    for region, period, cost in zip(costs["region"], costs["period"], costs["cost"]):
        efficiency.set(1.0, region=region, vintage=period)
        variable_cost.set(float(cost), region=region, vintage=period, period=period)

    return (
        TechnologyEntity(
            name=name,
            output_commodity=output_commodity,
            data_id=data_id,
            description=description,
            sector=sector,
        )
        .set_annual()
        .set_unlimited_capacity()
        .with_efficiency(
            input_commodity,
            efficiency,
            notes="Transfer technology, efficiency 1",
            units="PJ/PJ",
        )
        .with_lifetime(
            RegionalValuesArray(regions, fill=lifetime),
            notes="One period, so each vintage only supplies its own period",
        )
        .with_variable_cost(
            variable_cost,
            notes=str(costs["notes"].iloc[0]),
            data_quality=_COST_DATA_QUALITY,
            units=COST_UNITS,
        )
    )


def _add_emission_factors(
    technology: TechnologyEntity, input_commodity: str, factors: pd.DataFrame
):
    """Emit each gas of `factors` (columns `emission`, `factor`, `notes`,
    `reference`) per unit of `input_commodity`."""
    for emission, factor, notes, reference in zip(
        factors["emission"], factors["factor"], factors["notes"], factors["reference"]
    ):
        _ = technology.with_input_emission_factor(
            get_emission_commodity_name(emission),
            input_commodity,
            float(factor),
            # The data_source column references data_source_label; until the
            # provenance workflow is revised, the reference goes in the notes
            notes="; ".join(text for text in (notes, reference) if text) or None,
            data_quality=_EMISSION_DATA_QUALITY,
            units=EMISSION_UNITS,
        )


def _unique[T](values: Iterable[T]) -> list[T]:
    """Distinct values, in order of appearance"""
    return list(dict.fromkeys(values))

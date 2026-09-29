"""
Fuel prices: the delivered price of each (sector, fuel) and how it is split between
the import and the distribution technologies.

Each fuel is supplied in two steps, `F_ethos -> F_IMP_<FUEL> -> F_<fuel> ->
F_<S>_<FUEL> -> <S>_<fuel>`. The price a sector pays for a fuel (its delivered price)
is the variable cost of the import technology plus that of its distribution
technology. The `ImportPriceStrategy` chooses the import cost; each distribution
technology then costs its sector's delivered price minus it, so the delivered price
of every sector is the same whatever the strategy.
"""

from enum import StrEnum


class ImportPriceStrategy(StrEnum):
    """How the import cost of each fuel is chosen from the sectors' delivered prices."""

    CheapestConsumingSector = "cheapest_consuming_sector"
    """The lowest delivered price among the sectors that consume the fuel in the run.
    Reproduces the previous fuel module. The split depends on which sectors run: e.g.
    natural gas is imported at the electric power price when electricity runs, and at
    the industrial price when it doesn't."""

    CheapestPricedSector = "cheapest_priced_sector"
    """The lowest delivered price among all the sectors with a price for the fuel in
    the data, whether they run or not. The split does not depend on which sectors
    run."""

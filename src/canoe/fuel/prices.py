"""
Fuel prices: where the delivered price of each (sector, fuel) comes from, and how it
is split between the import and the distribution technologies.

Each fuel is supplied in two steps, `F_ethos -> F_IMP_<FUEL> -> F_<fuel> ->
F_<S>_<FUEL> -> <S>_<fuel>`. The price a sector pays for a fuel (its delivered price)
is the variable cost of the import technology plus that of its distribution
technology:

- The import cost of a fuel is the lowest delivered price among the entries of that
  fuel in `DELIVERED_PRICE_SOURCES`, whether their sectors run or not. The table is
  fixed, so the import cost doesn't change with the sectors that run.
- Each distribution technology costs its sector's delivered price minus the import
  cost.

Every unit imported goes through exactly one distribution technology (both with
efficiency 1), so the split only decides where the cost is reported: the price each
sector pays, and the model's solution, are the same whatever the split.
"""

from dataclasses import dataclass

from canoe.common import CANOEFuel, CANOESector


@dataclass(frozen=True)
class EIASeries:
    """
    An EIA AEO Table 3 'Energy Prices' series (real 2024 $/MMBtu), named by the CANOE
    sector and fuel it is read for (see `CANOESector.get_eia_sector` and
    `CANOEFuel.get_eia_fuel`).
    """

    sector: CANOESector
    fuel: CANOEFuel
    factor: float = 1.0
    """Multiplier on the series, for fuels priced as a fraction of another."""


@dataclass(frozen=True)
class ATBFuelCost:
    """The fuel cost of the NREL ATB technology of `fuel` (see
    `CANOEFuel.get_atb_technology`), constant over the periods."""

    fuel: CANOEFuel


@dataclass(frozen=True)
class FixedPrice:
    """A fixed price of `fuel` from a report (ethanol, renewable diesel, SPK),
    constant over the periods."""

    fuel: CANOEFuel


PriceSource = EIASeries | ATBFuelCost | FixedPrice

_S = CANOESector
_F = CANOEFuel

DELIVERED_PRICE_SOURCES: dict[tuple[CANOESector, CANOEFuel], PriceSource] = {
    # Electricity. No electricity sector yet, but its prices set import costs
    (_S.Electricity, _F.GaseousBioenergy): ATBFuelCost(_F.GaseousBioenergy),
    (_S.Electricity, _F.SolidBioenergy): ATBFuelCost(_F.SolidBioenergy),
    (_S.Electricity, _F.NaturalGas): EIASeries(_S.Electricity, _F.NaturalGas),
    (_S.Electricity, _F.Coal): EIASeries(_S.Industry, _F.Coal),
    (_S.Electricity, _F.Oil): EIASeries(_S.Electricity, _F.Oil),
    (_S.Electricity, _F.Diesel): EIASeries(_S.Electricity, _F.Diesel),
    (_S.Electricity, _F.NaturalUranium): ATBFuelCost(_F.NaturalUranium),
    (_S.Electricity, _F.EnrichedUranium): ATBFuelCost(_F.EnrichedUranium),
    (_S.Electricity, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
    # Residential
    (_S.Residential, _F.Oil): EIASeries(_S.Commercial, _F.Oil),
    (_S.Residential, _F.NaturalGas): EIASeries(_S.Residential, _F.NaturalGas),
    (_S.Residential, _F.LiquifiedPretroleumGas): EIASeries(_S.Residential, _F.Propane),
    (_S.Residential, _F.Wood): ATBFuelCost(_F.Wood),
    (_S.Residential, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Residential, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    # Commercial
    (_S.Commercial, _F.Oil): EIASeries(_S.Commercial, _F.Oil),
    (_S.Commercial, _F.NaturalGas): EIASeries(_S.Commercial, _F.NaturalGas),
    (_S.Commercial, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Commercial, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    # Industry
    (_S.Industry, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Industry, _F.Hydrogen): EIASeries(_S.Industry, _F.Hydrogen),
    (_S.Industry, _F.NaturalGas): EIASeries(_S.Industry, _F.NaturalGas),
    (_S.Industry, _F.HeavyFuelOil): EIASeries(_S.Industry, _F.HeavyFuelOil),
    (_S.Industry, _F.Coal): EIASeries(_S.Industry, _F.Coal),
    (_S.Industry, _F.Diesel): EIASeries(_S.Industry, _F.Diesel),
    (_S.Industry, _F.NaturalGasLiquids): EIASeries(_S.Industry, _F.Propane, 0.89),
    (_S.Industry, _F.PetroleumCoke): EIASeries(_S.Industry, _F.Coal),
    (_S.Industry, _F.Wood): ATBFuelCost(_F.Wood),
    (_S.Industry, _F.Coke): EIASeries(_S.Industry, _F.Coal),
    # Transportation
    (_S.Transportation, _F.BioEnergy): ATBFuelCost(_F.BioEnergy),
    (_S.Transportation, _F.Hydrogen): EIASeries(_S.Transportation, _F.Hydrogen),
    (_S.Transportation, _F.NaturalGas): EIASeries(_S.Transportation, _F.NaturalGas),
    (_S.Transportation, _F.HeavyFuelOil): EIASeries(_S.Transportation, _F.HeavyFuelOil),
    (_S.Transportation, _F.LiquifiedPretroleumGas): EIASeries(
        _S.Transportation, _F.Propane
    ),
    (_S.Transportation, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
    (_S.Transportation, _F.Ethanol): FixedPrice(_F.Ethanol),
    (_S.Transportation, _F.Diesel): EIASeries(_S.Transportation, _F.Diesel),
    (_S.Transportation, _F.RenewableDiesel): FixedPrice(_F.RenewableDiesel),
    (_S.Transportation, _F.CompressedNaturalGas): EIASeries(
        _S.Transportation, _F.NaturalGas, 0.89
    ),
    (_S.Transportation, _F.JetFuel): EIASeries(_S.Transportation, _F.JetFuel),
    (_S.Transportation, _F.SyntheticJetFuel): FixedPrice(_F.SyntheticJetFuel),
    (_S.Transportation, _F.MarineDieselOil): EIASeries(
        _S.Transportation, _F.Diesel, 0.9
    ),
    (_S.Transportation, _F.LiquifiedNaturalGas): EIASeries(
        _S.Transportation, _F.NaturalGas, 0.89
    ),
    # Agriculture: no EIA series of its own
    (_S.Agriculture, _F.NaturalGas): EIASeries(_S.Industry, _F.NaturalGas),
    (_S.Agriculture, _F.Diesel): EIASeries(_S.Transportation, _F.Diesel),
    (_S.Agriculture, _F.Propane): EIASeries(_S.Transportation, _F.Propane),
    (_S.Agriculture, _F.Gasoline): EIASeries(_S.Transportation, _F.Gasoline),
}
"""
Source of the delivered price of each (sector, fuel), reproducing the previous fuel
module (its `fuel_list.csv` rows and `_calc_cost` proxies). A (sector, fuel) that
is not here has no price. See `FUEL_MODULE_BUGS.md` for the quirks kept (proxy
series, the 0.89 and 0.9 factors).
"""

_PREVIOUS_MODULE_PRICE_SOURCE_ERRORS: dict[
    tuple[CANOESector, CANOEFuel], PriceSource
] = {
    # The previous module compared the output commodity with the technology name,
    # so residential LPG always took the transportation propane series
    (_S.Residential, _F.LiquifiedPretroleumGas): EIASeries(
        _S.Transportation, _F.Propane
    ),
}


def get_delivered_price_sources(
    reproduce_previous_price_errors: bool,
) -> dict[tuple[CANOESector, CANOEFuel], PriceSource]:
    """
    `DELIVERED_PRICE_SOURCES`, with the errors of the previous fuel module when
    `reproduce_previous_price_errors`.

    Examples
    --------
    >>> key = (CANOESector.Residential, CANOEFuel.LiquifiedPretroleumGas)
    >>> get_delivered_price_sources(False)[key]
    EIASeries(sector=<CANOESector.Residential: 'RES'>, fuel=Propane, factor=1.0)
    >>> get_delivered_price_sources(True)[key]
    EIASeries(sector=<CANOESector.Transportation: 'TRP'>, fuel=Propane, factor=1.0)
    """
    if not reproduce_previous_price_errors:
        return dict(DELIVERED_PRICE_SOURCES)
    return {**DELIVERED_PRICE_SOURCES, **_PREVIOUS_MODULE_PRICE_SOURCE_ERRORS}

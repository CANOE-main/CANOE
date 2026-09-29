import pytest

from canoe.common import CANOEFuel, CANOESector
from canoe.fuel.prices import (
    DELIVERED_PRICE_SOURCES,
    ATBFuelCost,
    EIASeries,
    FixedPrice,
    PriceSource,
    get_delivered_price_sources,
)

ALL_SOURCES = list(get_delivered_price_sources(True).items()) + list(
    DELIVERED_PRICE_SOURCES.items()
)


@pytest.mark.parametrize(("key", "source"), ALL_SOURCES)
def test_every_source_names_a_series(
    key: tuple[CANOESector, CANOEFuel], source: PriceSource
):
    if isinstance(source, EIASeries):
        assert source.sector.get_eia_sector() is not None
        assert source.fuel.get_eia_fuel(source.sector) is not None
    elif isinstance(source, ATBFuelCost):
        assert source.fuel.get_atb_technology() is not None
    else:
        assert isinstance(source, FixedPrice)
        assert source.fuel == key[1]


def test_no_price_for_electricity_or_other_fuels():
    fuels = {fuel for _, fuel in DELIVERED_PRICE_SOURCES}
    assert CANOEFuel.Electricity not in fuels
    assert CANOEFuel.Other not in fuels


def test_errors_only_change_existing_entries():
    assert get_delivered_price_sources(True).keys() == DELIVERED_PRICE_SOURCES.keys()

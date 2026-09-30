import pandas as pd
import pytest

from canoe.common import CANOEFuel, CANOESector
from canoe.fuel.emission_factors import (
    COMBUSTION_FACTOR_PROXIES,
    add_combustion_factor_proxies,
)
from canoe.fuel.loaders import get_combustion_emission_factors


def _rows(factors: pd.DataFrame, sector: CANOESector, fuel: CANOEFuel) -> pd.DataFrame:
    return factors.loc[factors["sector"].isin([sector]) & factors["fuel"].isin([fuel])]


def test_agriculture_gasoline_takes_transportation_factors():
    factors = add_combustion_factor_proxies(get_combustion_emission_factors(), False)
    agriculture = _rows(factors, CANOESector.Agriculture, CANOEFuel.Gasoline)
    transportation = _rows(factors, CANOESector.Transportation, CANOEFuel.Gasoline)
    assert len(agriculture) == 3
    assert (
        agriculture.set_index("emission")["factor"].to_dict()
        == transportation.set_index("emission")["factor"].to_dict()
    )


def test_previous_errors_leave_agriculture_gasoline_out():
    factors = add_combustion_factor_proxies(get_combustion_emission_factors(), True)
    assert _rows(factors, CANOESector.Agriculture, CANOEFuel.Gasoline).empty


@pytest.mark.parametrize(("key", "proxy"), COMBUSTION_FACTOR_PROXIES.items())
def test_proxies_fill_a_gap_with_existing_factors(
    key: tuple[CANOESector, CANOEFuel], proxy: tuple[CANOESector, CANOEFuel]
):
    factors = get_combustion_emission_factors()
    assert _rows(factors, *key).empty
    assert not _rows(factors, *proxy).empty


def test_rejects_proxy_of_a_pair_with_factors():
    factors = get_combustion_emission_factors()
    with_own = pd.concat(
        [
            factors,
            _rows(factors, CANOESector.Transportation, CANOEFuel.Gasoline).assign(
                sector=CANOESector.Agriculture
            ),
        ]
    )
    with pytest.raises(ValueError, match="remove its entry"):
        add_combustion_factor_proxies(with_own, False)

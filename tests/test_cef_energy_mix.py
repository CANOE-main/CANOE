import pandas as pd
import pytest

from canoe.cef.energy_mix import (
    SmallShareStrategy,
    compute_demand_and_splits,
    energy_use_by_period,
)
from canoe.common import CANOEFuel, CANOEProvince

ON = CANOEProvince.ONTARIO
QC = CANOEProvince.QUEBEC


def _energy(rows: list[tuple[CANOEProvince, int, CANOEFuel, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["region", "period", "fuel", "value"])


@pytest.fixture
def energy() -> pd.DataFrame:
    # ON: NG small in every period, ELC small only in 2025; QC: no hydrogen use
    return _energy(
        [
            (ON, 2025, CANOEFuel.Gasoline, 97.0),
            (ON, 2025, CANOEFuel.Electricity, 2.0),
            (ON, 2025, CANOEFuel.NaturalGas, 1.0),
            (ON, 2030, CANOEFuel.Gasoline, 90.0),
            (ON, 2030, CANOEFuel.Electricity, 9.0),
            (ON, 2030, CANOEFuel.NaturalGas, 1.0),
            (QC, 2025, CANOEFuel.Electricity, 60.0),
            (QC, 2025, CANOEFuel.Hydrogen, 0.0),
            (QC, 2025, CANOEFuel.Gasoline, 40.0),
            (QC, 2030, CANOEFuel.Electricity, 70.0),
            (QC, 2030, CANOEFuel.Hydrogen, 0.0),
            (QC, 2030, CANOEFuel.Gasoline, 30.0),
        ]
    )


def _splits_of(splits: pd.DataFrame, region: CANOEProvince, period: int):
    rows = splits.loc[splits["region"].isin([region]) & (splits["period"] == period)]
    return dict(zip(rows["fuel"], rows["split"].round(6)))


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_splits_add_up_to_one(energy: pd.DataFrame, strategy: SmallShareStrategy):
    _, splits = compute_demand_and_splits(energy, 0.05, strategy)
    totals = splits.groupby(["region", "period"])["split"].sum()
    assert totals.round(12).eq(1).all()


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_unused_and_always_small_fuels_left_out(
    energy: pd.DataFrame, strategy: SmallShareStrategy
):
    _, splits = compute_demand_and_splits(energy, 0.05, strategy)
    assert not splits["fuel"].isin([CANOEFuel.NaturalGas, CANOEFuel.Hydrogen]).any()


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_small_fuel_gets_zero_split_where_small(
    energy: pd.DataFrame, strategy: SmallShareStrategy
):
    # ELC is above the threshold in 2030, so it keeps a (zero) split in 2025
    _, splits = compute_demand_and_splits(energy, 0.05, strategy)
    assert _splits_of(splits, ON, 2025)[CANOEFuel.Electricity] == 0.0
    assert _splits_of(splits, ON, 2025)[CANOEFuel.Gasoline] == 1.0


def test_zero_small_shares_keeps_the_total(energy: pd.DataFrame):
    demand, splits = compute_demand_and_splits(
        energy, 0.05, SmallShareStrategy.ZeroSmallShares
    )
    assert demand.loc[demand["region"].isin([ON]), "demand"].tolist() == [100.0, 100.0]
    # Shares of the full total, scaled up over the fuels kept
    assert _splits_of(splits, ON, 2030) == {
        CANOEFuel.Gasoline: round(0.90 / 0.99, 6),
        CANOEFuel.Electricity: round(0.09 / 0.99, 6),
    }


def test_drop_small_fuels_removes_their_energy(energy: pd.DataFrame):
    demand, splits = compute_demand_and_splits(
        energy, 0.05, SmallShareStrategy.DropSmallFuels
    )
    assert demand.loc[demand["region"].isin([ON]), "demand"].tolist() == [99.0, 99.0]
    assert _splits_of(splits, ON, 2030) == {
        CANOEFuel.Gasoline: round(90 / 99, 6),
        CANOEFuel.Electricity: round(9 / 99, 6),
    }


def test_drop_small_fuels_threshold_comparisons():
    # Exactly at the threshold: kept over the horizon (>=), zeroed in the period (>)
    energy = _energy(
        [
            (ON, 2025, CANOEFuel.Gasoline, 90.0),
            (ON, 2025, CANOEFuel.Electricity, 10.0),
        ]
    )
    _, drop = compute_demand_and_splits(energy, 0.1, SmallShareStrategy.DropSmallFuels)
    _, zero = compute_demand_and_splits(energy, 0.1, SmallShareStrategy.ZeroSmallShares)
    assert _splits_of(drop, ON, 2025)[CANOEFuel.Electricity] == 0.0
    assert _splits_of(zero, ON, 2025)[CANOEFuel.Electricity] == 0.1


def test_every_share_small_raises():
    energy = _energy(
        [
            (ON, 2025, CANOEFuel.Gasoline, 40.0),
            (ON, 2025, CANOEFuel.Diesel, 30.0),
            (ON, 2025, CANOEFuel.Electricity, 30.0),
            (ON, 2030, CANOEFuel.Gasoline, 60.0),
            (ON, 2030, CANOEFuel.Diesel, 20.0),
            (ON, 2030, CANOEFuel.Electricity, 20.0),
        ]
    )
    with pytest.raises(ValueError, match="every fuel share is below"):
        compute_demand_and_splits(energy, 0.5, SmallShareStrategy.ZeroSmallShares)


def _all_small(region: CANOEProvince, periods: list[int]):
    # Three fuels, none reaching a 0.5 threshold
    return [
        (region, period, fuel, value)
        for period in periods
        for fuel, value in [
            (CANOEFuel.Gasoline, 40.0),
            (CANOEFuel.Diesel, 30.0),
            (CANOEFuel.Electricity, 30.0),
        ]
    ]


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_province_small_in_every_period_raises(strategy: SmallShareStrategy):
    # ON takes no fuel at all, so it has no row among the taken fuels; QC is fine
    energy = _energy(
        _all_small(ON, [2025, 2030])
        + [
            (QC, 2025, CANOEFuel.Electricity, 60.0),
            (QC, 2025, CANOEFuel.Gasoline, 40.0),
            (QC, 2030, CANOEFuel.Electricity, 70.0),
            (QC, 2030, CANOEFuel.Gasoline, 30.0),
        ]
    )
    with pytest.raises(ValueError, match="every fuel share is below.*Ontario 2025"):
        compute_demand_and_splits(energy, 0.5, strategy)


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_every_province_small_raises(strategy: SmallShareStrategy):
    energy = _energy(_all_small(ON, [2025, 2030]))
    with pytest.raises(ValueError, match="every fuel share is below"):
        compute_demand_and_splits(energy, 0.5, strategy)


@pytest.mark.parametrize("strategy", list(SmallShareStrategy))
def test_every_share_at_the_threshold_raises_or_keeps_shares(
    strategy: SmallShareStrategy,
):
    # Shares exactly at the threshold are taken (>=), but drop_small_fuels zeroes
    # them in the period (not > threshold): no split may be NaN either way
    energy = _energy(
        [
            (ON, 2025, CANOEFuel.Gasoline, 50.0),
            (ON, 2025, CANOEFuel.Electricity, 50.0),
        ]
    )
    if strategy == SmallShareStrategy.DropSmallFuels:
        with pytest.raises(ValueError, match="every fuel share is below"):
            compute_demand_and_splits(energy, 0.5, strategy)
    else:
        _, splits = compute_demand_and_splits(energy, 0.5, strategy)
        assert _splits_of(splits, ON, 2025) == {
            CANOEFuel.Gasoline: 0.5,
            CANOEFuel.Electricity: 0.5,
        }


def test_energy_use_by_period_fails_on_missing_years():
    energy = pd.DataFrame(
        {"region": ON, "year": [2045, 2050], "fuel": CANOEFuel.Gasoline, "value": 1.0}
    )
    with pytest.raises(ValueError, match=r"no data for the years \[2055\]"):
        energy_use_by_period(energy, {2045: 2050, 2050: 2055})

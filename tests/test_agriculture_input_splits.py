import pandas as pd
import pytest

from canoe.agriculture.input_splits import (
    InputSplitStrategy,
    compute_input_splits,
    energy_with_remainder_splits,
    nrcan_percent_with_remainder_splits,
)
from canoe.common import CANOEFuel, CANOEProvince

ELC, NG, DSL = CANOEFuel.Electricity, CANOEFuel.NaturalGas, CANOEFuel.Diesel


class TestNRCanPercentWithRemainder:
    def test_excess_over_one_comes_off_the_smallest_share(self):
        splits = nrcan_percent_with_remainder_splits(
            {ELC: 0.5, NG: 0.3, DSL: 0.21}, DSL
        )
        assert splits == {ELC: 0.5, NG: 0.3, DSL: 0.2}

    def test_remainder_fuel_without_share_is_added(self):
        splits = nrcan_percent_with_remainder_splits({ELC: 0.6, DSL: 0.0}, DSL)
        assert splits == {ELC: 0.6, DSL: 0.399}

    def test_zero_shares_are_left_out(self):
        splits = nrcan_percent_with_remainder_splits({ELC: 0.6, NG: 0.0, DSL: 0.3}, DSL)
        assert NG not in splits


class TestEnergyWithRemainder:
    def test_remainder_fuel_without_energy_use_takes_the_rest(self):
        splits = energy_with_remainder_splits({ELC: 3.0, DSL: 0.0}, 4.0, DSL)
        assert splits == {ELC: 0.75, DSL: 0.25}


def _energy_use_by_source(energy: dict[CANOEFuel | None, float]) -> pd.DataFrame:
    total = sum(energy.values())
    return pd.DataFrame(
        {
            "province": CANOEProvince.ONTARIO,
            "source": [str(f) for f in energy],
            "fuel": list(energy),
            "energy_use": list(energy.values()),
            "share": [e / total for e in energy.values()],
        }
    )


class TestComputeInputSplits:
    def test_same_splits_in_every_period(self):
        by_source = _energy_use_by_source({ELC: 1.0, NG: 3.0, None: 1.0})
        splits = compute_input_splits(
            by_source,
            [ELC, NG],
            InputSplitStrategy.EnergyNormalized,
            DSL,
            [2025, 2030],
        )
        assert list(splits.columns) == ["region", "period", "fuel", "split"]
        assert len(splits) == 4
        assert splits.groupby("period")["split"].sum().tolist() == [1.0, 1.0]

    def test_province_using_none_of_the_fuels(self):
        by_source = _energy_use_by_source({ELC: 0.0, NG: 0.0, None: 1.0})
        with pytest.raises(ValueError, match="uses none of the requested"):
            compute_input_splits(
                by_source, [ELC, NG], InputSplitStrategy.EnergyNormalized, DSL, [2025]
            )

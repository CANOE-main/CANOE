import numpy as np
import pytest

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintagePeriodArray,
)
from canoe.common import CANOEProvince

REGIONS = [CANOEProvince.ONTARIO, CANOEProvince.QUEBEC]
VINTAGES = [2020, 2021, 2022]
PERIODS = [2020, 2021, 2022, 2023]


@pytest.fixture
def arr():
    a = RegionVintagePeriodArray(REGIONS, VINTAGES, PERIODS)
    a.data[:] = 1.0  # fill everything with a known value
    return a


# --- mask_out_period_before_vintage ---


class TestMaskOutPeriodBeforeVintage:
    def test_masked_cells_are_nan(self, arr):
        arr.mask_out_period_before_vintage()
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if period < vintage:
                    assert np.all(np.isnan(arr.data[:, v_idx, p_idx]))

    def test_unmasked_cells_are_unchanged(self, arr):
        arr.mask_out_period_before_vintage()
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if period >= vintage:
                    assert np.all(arr.data[:, v_idx, p_idx] == 1.0)

    def test_custom_fill_value(self, arr):
        arr.mask_out_period_before_vintage(fill=-999.0)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if period < vintage:
                    assert np.all(arr.data[:, v_idx, p_idx] == -999.0)

    def test_period_equal_vintage_not_masked(self, arr):
        """period == vintage should NOT be masked (condition is strictly <)."""
        arr.mask_out_period_before_vintage()
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if period == vintage:
                    assert np.all(arr.data[:, v_idx, p_idx] == 1.0)

    def test_idempotent(self, arr):
        arr.mask_out_period_before_vintage()
        data_after_first = arr.data.copy()
        arr.mask_out_period_before_vintage()
        np.testing.assert_array_equal(arr.data, data_after_first)


# --- mask_out_after_life ---


class TestMaskAfterLife:
    def test_masked_cells_are_nan(self, arr):
        life = 2
        arr.mask_out_after_life(life)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage + life <= period:
                    assert np.all(np.isnan(arr.data[:, v_idx, p_idx]))

    def test_unmasked_cells_are_unchanged(self, arr):
        life = 2
        arr.mask_out_after_life(life)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage + life > period:
                    assert np.all(arr.data[:, v_idx, p_idx] == 1.0)

    def test_boundary_is_masked(self, arr):
        """vintage + life == period should be masked (condition is <=)."""
        life = 2
        arr.mask_out_after_life(life)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage + life == period:
                    assert np.all(np.isnan(arr.data[:, v_idx, p_idx]))

    def test_custom_fill_value(self, arr):
        arr.mask_out_after_life(2, fill=0.0)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage + 2 <= period:
                    assert np.all(arr.data[:, v_idx, p_idx] == 0.0)

    def test_large_life_masks_nothing(self, arr):
        """A life larger than the period range should leave everything unmasked."""
        arr.mask_out_after_life(life=9999)
        assert np.all(arr.data == 1.0)

    def test_zero_life_masks_period_equal_vintage(self, arr):
        """life=0 means vintage + 0 <= period, so period >= vintage is masked."""
        arr.mask_out_after_life(life=0)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage <= period:
                    assert np.all(np.isnan(arr.data[:, v_idx, p_idx]))

    def test_regional_life(self, arr):
        """Each region is masked with its own lifetime."""
        life = RegionalValuesArray(REGIONS)
        life.set(1, region=CANOEProvince.ONTARIO)
        life.set(3, region=CANOEProvince.QUEBEC)
        arr.mask_out_after_life(life)
        for r_idx, region_life in enumerate([1, 3]):
            for v_idx, vintage in enumerate(VINTAGES):
                for p_idx, period in enumerate(PERIODS):
                    masked = np.isnan(arr.data[r_idx, v_idx, p_idx])
                    assert masked == (vintage + region_life <= period)


# --- combined ---


# --- combined ---


class TestCombined:
    def test_both_masks_leave_valid_window(self, arr):
        """After both masks, only vintage <= period < vintage + life should survive."""
        life = 2
        arr.mask_out_period_before_vintage()
        arr.mask_out_after_life(life)
        for v_idx, vintage in enumerate(VINTAGES):
            for p_idx, period in enumerate(PERIODS):
                if vintage <= period < vintage + life:
                    assert np.all(arr.data[:, v_idx, p_idx] == 1.0)
                else:
                    assert np.all(np.isnan(arr.data[:, v_idx, p_idx]))

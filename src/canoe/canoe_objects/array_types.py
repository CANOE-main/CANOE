import numpy as np

from canoe.canoe_objects.demand import LabeledArray
from canoe.common import CANOEProvince


class RegionalValuesArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
        }
        super().__init__(coords, fill)


class RegionPeriodArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        period: list[int],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
            "period": period,
        }
        super().__init__(coords, fill)


class RegionVintageArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        vintage: list[int],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
            "vintage": vintage,
        }
        super().__init__(coords, fill)


class RegionVintagePeriodArray(LabeledArray):
    def __init__(
        self,
        region: list[CANOEProvince],
        vintage: list[int],
        period: list[int],
        fill: float = np.nan,
    ):
        coords = {
            "region": region,
            "vintage": vintage,
            "period": period,
        }
        super().__init__(coords, fill)

    def mask_out_period_before_vintage(self, fill: float = np.nan):
        periods = np.array(self.coords["period"])
        vintages = np.array(self.coords["vintage"])

        period_axis = self.dims.index("period")
        vintage_axis = self.dims.index("vintage")

        # Compare period vs vintage along their respective axes in the full N-D array
        p_shape = [1] * len(self.dims)
        p_shape[period_axis] = len(periods)
        v_shape = [1] * len(self.dims)
        v_shape[vintage_axis] = len(vintages)

        p = periods.reshape(p_shape)
        v = vintages.reshape(v_shape)

        mask = np.broadcast_to(p < v, self.shape)
        self.data[mask] = fill
        return self

    def mask_out_after_life(self, life: float, fill: float = np.nan):
        periods = np.array(self.coords["period"])
        vintages = np.array(self.coords["vintage"])

        period_axis = self.dims.index("period")
        vintage_axis = self.dims.index("vintage")

        p_shape = [1] * len(self.dims)
        p_shape[period_axis] = len(periods)
        v_shape = [1] * len(self.dims)
        v_shape[vintage_axis] = len(vintages)

        p = periods.reshape(p_shape)
        v = vintages.reshape(v_shape)

        mask = np.broadcast_to(v + life <= p, self.shape)
        self.data[mask] = fill
        return self

import numpy as np

from canoe.canoe_objects.labeled_array import LabeledArray
from canoe.common import CANOEProvince


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

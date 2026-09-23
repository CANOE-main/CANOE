import pytest
from canoe_schema.v4_0 import CommodityTypeCode

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionPeriodArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.fuel_serving_tech import (
    FuelGrouping,
    FuelServingTechnologyEntity,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier

REGIONS = [CANOEProvince.ONTARIO, CANOEProvince.QUEBEC]
DATA_ID = DatasetIdentifier(CANOESector.Commercial, "TEST", "000")


def _technology() -> TechnologyEntity:
    return TechnologyEntity("TECH", "OUT", DATA_ID)


def _efficiency(vintages: list[int], value: float = 1.0) -> RegionVintageArray:
    return RegionVintageArray(REGIONS, vintages, fill=value)


class TestTechnologyEntityValidation:
    def test_valid_technology(self):
        _technology().with_efficiency("IN", _efficiency([2020])).validate()

    def test_no_inputs(self):
        with pytest.raises(ValueError, match="no inputs"):
            _technology().validate()

    def test_non_positive_efficiency(self):
        technology = _technology().with_efficiency("IN", _efficiency([2020], 0.0))
        with pytest.raises(ValueError, match="non-positive efficiency"):
            technology.validate()

    def test_split_for_unknown_input(self):
        technology = (
            _technology()
            .with_efficiency("IN", _efficiency([2020]))
            .with_input_split("OTHER", RegionPeriodArray(REGIONS, [2025], fill=0.5))
        )
        with pytest.raises(ValueError, match="not inputs"):
            technology.validate()

    def test_splits_add_up_to_more_than_one(self):
        technology = (
            _technology()
            .with_efficiency("A", _efficiency([2020]))
            .with_efficiency("B", _efficiency([2020]))
            .with_input_split("A", RegionPeriodArray(REGIONS, [2025], fill=0.6))
            .with_input_split("B", RegionPeriodArray(REGIONS, [2025], fill=0.6))
        )
        with pytest.raises(ValueError, match="add up to"):
            technology.validate()

    def test_existing_capacity_without_efficiency(self):
        technology = (
            _technology()
            .with_efficiency("IN", _efficiency([2020]))
            .with_existing_capacity(RegionVintageArray(REGIONS, [2015], fill=1.0))
        )
        with pytest.raises(ValueError, match="existing capacity without efficiency"):
            technology.validate()

    def test_fixed_cost_before_vintage(self):
        technology = (
            _technology()
            .with_efficiency("IN", _efficiency([2030]))
            .with_fixed_cost(RegionVintagePeriodArray(REGIONS, [2030], [2025], fill=1))
        )
        with pytest.raises(ValueError, match="before vintage"):
            technology.validate()

    def test_fixed_cost_after_end_of_life(self):
        technology = (
            _technology()
            .with_efficiency("IN", _efficiency([2020]))
            .with_lifetime(RegionalValuesArray(REGIONS, fill=10))
            .with_fixed_cost(RegionVintagePeriodArray(REGIONS, [2020], [2030], fill=1))
        )
        with pytest.raises(ValueError, match="end of life"):
            technology.validate()


FUELS = [CANOEFuel.Electricity, CANOEFuel.NaturalGas]


def _fuel_serving(grouping: FuelGrouping) -> FuelServingTechnologyEntity:
    return FuelServingTechnologyEntity(
        sector=CANOESector.Commercial,
        short_desc="OTH",
        fuels=FUELS,
        fuel_import_flag={f: CommodityTypeCode.A for f in FUELS},
        output_commodity_name="OUT",
        data_id=DATA_ID,
        grouping=grouping,
    )


class TestFuelGrouping:
    def test_per_fuel_builds_one_technology_per_fuel(self):
        entity = _fuel_serving(FuelGrouping.PerFuel).with_efficiencies(
            {f: _efficiency([2025]) for f in FUELS}
        )
        technologies = entity.to_technology_entities()
        assert [t.name for t in technologies] == ["C_OTH_ELC", "C_OTH_NG"]
        assert all(len(t.inputs) == 1 for t in technologies)

    def test_shared_builds_one_technology_with_all_inputs(self):
        entity = (
            _fuel_serving(FuelGrouping.Shared)
            .with_efficiencies({f: _efficiency([2025]) for f in FUELS})
            .with_input_splits(
                {f: RegionPeriodArray(REGIONS, [2025], fill=0.5) for f in FUELS}
            )
            .with_lifetimes(RegionalValuesArray(REGIONS, fill=10))
        )
        (technology,) = entity.to_technology_entities()
        assert technology.name == "C_OTH"
        assert len(technology.inputs) == 2
        assert len(technology.input_splits) == 2
        technology.validate()

    def test_shared_rejects_per_fuel_technology_values(self):
        entity = _fuel_serving(FuelGrouping.Shared)
        with pytest.raises(TypeError, match="single array"):
            entity.with_lifetimes({f: RegionalValuesArray(REGIONS) for f in FUELS})

    def test_per_fuel_rejects_single_array(self):
        entity = _fuel_serving(FuelGrouping.PerFuel)
        with pytest.raises(TypeError, match="dict of values by fuel"):
            entity.with_lifetimes(RegionalValuesArray(REGIONS))

    def test_per_fuel_rejects_input_splits(self):
        entity = _fuel_serving(FuelGrouping.PerFuel)
        with pytest.raises(ValueError, match="Shared"):
            entity.with_input_splits({})

    def test_missing_fuel_values(self):
        entity = _fuel_serving(FuelGrouping.PerFuel)
        with pytest.raises(ValueError, match="missing values"):
            entity.with_efficiencies({CANOEFuel.Electricity: _efficiency([2025])})

"""
Consistency of the residential technology catalog with itself and with the data it
points to (module data in `residential/data`, not the data lake cache).
"""

import pytest

from canoe.common import CANOEProvince
from canoe.residential.end_uses import ResidentialEndUse
from canoe.residential.loaders import (
    get_aeo_lighting_data,
    get_aeo_technology_menu,
    get_ceud_appliance_stock,
    get_ceud_cooling_systems,
    get_ceud_heating_system_stock,
    get_ceud_water_heater_stock,
    get_ontario_lighting_shares,
)
from canoe.residential.technology_catalog import ExistingTechnology, NewTechnology


class TestNewTechnologies:
    def test_unique_names(self):
        names = [t.spec().name for t in NewTechnology]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("technology", list(NewTechnology))
    def test_equivalents_serve_its_end_uses(self, technology: NewTechnology):
        spec = technology.spec()
        if spec.lamp is not None:
            assert spec.equivalents == {}
            assert spec.end_uses == (ResidentialEndUse.Lighting,)
            return
        assert tuple(spec.equivalents) == spec.end_uses
        for end_use, existing in spec.equivalents.items():
            assert existing.spec().end_use == end_use

    def test_aeo_classes_and_equipment_exist(self):
        menu = get_aeo_technology_menu()
        classes = set(menu.classes["equipment_class"])
        equipment = set(menu.equipment["equipment"])
        for technology in NewTechnology:
            spec = technology.spec()
            if spec.lamp is None:
                assert spec.aeo_class in classes, technology
                assert spec.aeo_equipment in equipment, technology

    def test_lamps_exist_in_lighting_data(self):
        lamps = set(get_aeo_lighting_data()["lamp"])
        for technology in NewTechnology:
            if technology.spec().lamp is not None:
                assert technology.spec().lamp in lamps, technology


class TestExistingTechnologies:
    def test_unique_names(self):
        assert len(set(ExistingTechnology)) == len(list(ExistingTechnology))

    def test_new_equivalent_shares_the_end_use(self):
        for technology in ExistingTechnology:
            equivalent = technology.spec().new_equivalent
            if equivalent is None:
                assert technology == ExistingTechnology.OtherAppliances
                continue
            # The wood water heater takes the wood stove's class (no AEO wood heater)
            if technology == ExistingTechnology.WoodWaterHeater:
                assert equivalent == NewTechnology.WoodStove
                continue
            assert technology.spec().end_use in equivalent.end_uses()

    def test_nrcan_rows_exist(self):
        ontario = CANOEProvince.ONTARIO
        rows = {
            ResidentialEndUse.SpaceHeating: set(
                get_ceud_heating_system_stock(ontario, 2022).index
            ),
            ResidentialEndUse.SpaceCooling: set(
                get_ceud_cooling_systems(ontario, 2022).stock.index
            ),
            ResidentialEndUse.WaterHeating: set(
                get_ceud_water_heater_stock(ontario, 2022).index
            ),
        }
        appliances = get_ceud_appliance_stock(ontario, 2022)
        lamps = set(get_ontario_lighting_shares()["lamp"])
        for technology in ExistingTechnology:
            spec = technology.spec()
            if spec.end_use == ResidentialEndUse.Lighting:
                assert spec.lamp in lamps, technology
            elif spec.end_use.is_appliance():
                fuel = spec.fuels[0].get_desc_name()
                stock = appliances[appliances["fuel"] == fuel]
                assert set(spec.nrcan_rows) <= set(stock["appliance"]), technology
            else:
                assert set(spec.nrcan_rows) <= rows[spec.end_use], technology

    def test_every_end_use_has_existing_technologies(self):
        served = {t.spec().end_use for t in ExistingTechnology}
        assert served == set(ResidentialEndUse)

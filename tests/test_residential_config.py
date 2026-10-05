import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from canoe.common import CANOEProvince
from canoe.common.gdp import GDPProjectionPoint
from canoe.initializer import CANOEBaseConfig
from canoe.residential.config import CANOEResidentialConfig
from canoe.residential.demand import DemandDriver
from canoe.residential.end_uses import APPLIANCES, ResidentialEndUse
from canoe.residential.technology_catalog import CensusDivision, NewTechnology
from canoe.sector_config import resolve_sector_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"
DEFAULT_CONFIG = CONFIGURATION / "residential-default.toml"


@pytest.fixture
def base() -> CANOEBaseConfig:
    with (CONFIGURATION / "full-pipeline.toml").open("rb") as f:
        return CANOEBaseConfig.model_validate(tomllib.load(f)["compiler"]["base"])


def _raw() -> dict[str, Any]:
    with DEFAULT_CONFIG.open("rb") as f:
        return tomllib.load(f)


def _config(base: CANOEBaseConfig, **overrides: Any) -> CANOEResidentialConfig:
    return resolve_sector_config({**_raw(), **overrides}, base)


def _with_end_uses(base: CANOEBaseConfig, end_uses: dict[str, Any]):
    return _config(base, end_uses=end_uses)


class TestDefaultConfig:
    def test_resolves_to_residential_with_inherited_fields(self, base: CANOEBaseConfig):
        config = resolve_sector_config(DEFAULT_CONFIG, base)
        assert isinstance(config, CANOEResidentialConfig)
        assert config.data_version == base.data_version
        assert config.provinces == base.provinces
        assert config.period_step == base.period_step
        assert config.demand_projection_point == GDPProjectionPoint.PeriodEnd
        assert config.get_dataset_code() == f"RESHR{base.data_version}"

    def test_every_end_use_modelled(self, base: CANOEBaseConfig):
        config = _config(base)
        assert config.end_uses.enabled() == list(ResidentialEndUse)
        assert config.demand_driver == DemandDriver.Population
        assert config.include_dsd

    def test_new_technologies_of_the_previous_module(self, base: CANOEBaseConfig):
        new_technologies = _config(base).end_uses.new_technologies()
        assert len(new_technologies) == 21
        # Heat pumps serve both space heating and space cooling
        assert new_technologies[NewTechnology.AirSourceHeatPump] == [
            ResidentialEndUse.SpaceHeating,
            ResidentialEndUse.SpaceCooling,
        ]
        assert new_technologies[NewTechnology.SolarWaterHeater] == [
            ResidentialEndUse.WaterHeating
        ]

    def test_weather_mapping_of_space_conditioning_only(self, base: CANOEBaseConfig):
        mapping = _config(base).end_uses.weather_mapping()
        assert {e for e, mapped in mapping.items() if mapped} == {
            ResidentialEndUse.SpaceHeating,
            ResidentialEndUse.SpaceCooling,
        }

    def test_province_mappings(self, base: CANOEBaseConfig):
        config = _config(base)
        assert config.resstock_us_states[CANOEProvince.ONTARIO] == "MI"
        assert config.aeo_census_divisions[CANOEProvince.ONTARIO].aeo_number() == 3
        assert config.aeo_census_divisions[CANOEProvince.SASKATCHEWAN] == (
            CensusDivision.WestNorthCentral
        )


class TestEndUses:
    def test_missing_table_leaves_end_uses_out(self, base: CANOEBaseConfig):
        config = _with_end_uses(base, {"lighting": {}, "appliances": {}})
        assert config.end_uses.enabled() == [ResidentialEndUse.Lighting, *APPLIANCES]

    def test_heat_pump_under_one_table_serves_only_it(self, base: CANOEBaseConfig):
        config = _with_end_uses(
            base,
            {
                "space heating": {
                    "new_technologies": ["air-source heat pump high efficiency"]
                }
            },
        )
        assert config.end_uses.new_technologies() == {
            NewTechnology.AirSourceHeatPumpHighEfficiency: [
                ResidentialEndUse.SpaceHeating
            ]
        }

    def test_rejects_technology_of_another_end_use(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="cannot serve space cooling"):
            _with_end_uses(
                base,
                {"space cooling": {"new_technologies": ["natural gas furnace"]}},
            )
        with pytest.raises(ValidationError, match="cannot serve"):
            _with_end_uses(
                base,
                {"appliances": {"new_technologies": ["led bulb"]}},
            )

    def test_rejects_duplicate_technologies(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="more than once"):
            _with_end_uses(
                base,
                {"lighting": {"new_technologies": ["halogen bulb", "halogen bulb"]}},
            )

    def test_rejects_unknown_technology_or_option(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError):
            _with_end_uses(base, {"lighting": {"new_technologies": ["oil lamp"]}})
        with pytest.raises(ValidationError):
            _with_end_uses(base, {"lighting": {"apply_weather_mapping": True}})
        with pytest.raises(ValidationError):
            _with_end_uses(base, {"cooking": {}})

    def test_rejects_no_end_use(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="at least one end use"):
            _with_end_uses(base, {})

    def test_capacity_factors_are_fractions(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError):
            _with_end_uses(base, {"appliances": {"annual_capacity_factor": 1.5}})


class TestSectorOptions:
    def test_gdp_driver(self, base: CANOEBaseConfig):
        assert _config(base, demand_driver="gdp").demand_driver == DemandDriver.GDP
        with pytest.raises(ValidationError):
            _config(base, demand_driver="households")

    def test_rejects_province_without_mapping(self, base: CANOEBaseConfig):
        states = _raw()["resstock_us_states"]
        del states["ON"]
        with pytest.raises(ValidationError, match="resstock_us_states has no entry"):
            _config(base, resstock_us_states=states)

    def test_mapping_only_for_configured_provinces(self, base: CANOEBaseConfig):
        config = _config(base, provinces=["ON"])
        assert config.provinces == [CANOEProvince.ONTARIO]

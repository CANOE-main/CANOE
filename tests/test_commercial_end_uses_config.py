import tomllib
from pathlib import Path

import pytest
from canoe_schema.v4_0 import OperatorCode
from pydantic import ValidationError

from canoe.canoe_objects.fuel_serving_tech import FuelGrouping
from canoe.commercial.config import (
    EndUsesConfig,
    SpaceConditioningEndUseConfig,
)
from canoe.commercial.end_uses import CommercialEndUse
from canoe.commercial.technology_catalog import (
    NEW_TECHNOLOGIES,
    NewTechnology,
)
from canoe.common import CANOEFuel

DEFAULT_CONFIG = Path(__file__).parents[1] / "configuration" / "commercial-default.toml"


def _parse(toml: str) -> EndUsesConfig:
    return EndUsesConfig.model_validate(tomllib.loads(toml)["end_uses"])


class TestEndUsesConfig:
    def test_tables_enable_end_uses_in_fixed_order(self):
        config = _parse(
            """
            [end_uses.other]
            fuels = ["ELC"]
            [end_uses."space heating"]
            existing_fuels = ["NG", "ELC"]
            """
        )
        assert config.enabled() == [
            CommercialEndUse.SpaceHeating,
            CommercialEndUse.Other,
        ]

    def test_space_conditioning_only_includes_heating_and_cooling(self):
        config = _parse(
            """
            [end_uses."space cooling"]
            existing_fuels = ["ELC"]
            [end_uses.other]
            fuels = ["ELC"]
            """
        )
        space_conditioning = config.space_conditioning()
        assert list(space_conditioning) == [CommercialEndUse.SpaceCooling]
        assert isinstance(
            space_conditioning[CommercialEndUse.SpaceCooling],
            SpaceConditioningEndUseConfig,
        )
        assert space_conditioning[CommercialEndUse.SpaceCooling].existing_fuels == [
            CANOEFuel.Electricity
        ]

    def test_weather_mapping_defaults_to_false(self):
        config = _parse(
            """
            [end_uses."space heating"]
            apply_weather_mapping = true
            existing_fuels = ["NG"]
            [end_uses.other]
            fuels = ["ELC"]
            """
        )
        assert config.weather_mapping() == {
            CommercialEndUse.SpaceHeating: True,
            CommercialEndUse.Other: False,
        }

    def test_misspelled_end_use_is_rejected(self):
        with pytest.raises(ValidationError):
            _parse(
                """
                [end_uses."space heatin"]
                existing_fuels = ["NG"]
                """
            )

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError):
            _parse(
                """
                [end_uses.other]
                fuels = ["ELC"]
                existing_fuels = ["NG"]
                """
            )


class TestOtherEndUseConfig:
    def test_defaults(self):
        other = _parse(
            """
            [end_uses.other]
            fuels = ["ELC", "NG"]
            """
        ).other
        assert other is not None
        assert other.technology_grouping == FuelGrouping.Shared
        assert other.input_split_operator == OperatorCode.LE
        assert other.electrification is None

    def test_electrification_table(self):
        other = _parse(
            """
            [end_uses.other]
            fuels = ["ELC", "NG"]
            [end_uses.other.electrification]
            factor = 0.62
            """
        ).other
        assert other is not None and other.electrification is not None
        assert other.electrification.factor == 0.62

    def test_per_fuel_without_split_options(self):
        other = _parse(
            """
            [end_uses.other]
            fuels = ["ELC", "NG"]
            technology_grouping = "per_fuel"
            """
        ).other
        assert other is not None
        assert other.technology_grouping == FuelGrouping.PerFuel

    @pytest.mark.parametrize(
        "option",
        ['input_split_operator = "le"', "electrification = { factor = 0.5 }"],
    )
    def test_per_fuel_rejects_shared_only_options(self, option: str):
        with pytest.raises(ValidationError, match="only apply to"):
            _parse(
                f"""
                [end_uses.other]
                fuels = ["ELC", "NG"]
                technology_grouping = "per_fuel"
                {option}
                """
            )

    def test_fuels_are_required(self):
        with pytest.raises(ValidationError):
            _parse(
                """
                [end_uses.other]
                """
            )


class TestNewTechnologiesConfig:
    def test_default_is_no_new_technologies(self):
        config = _parse(
            """
            [end_uses."space heating"]
            existing_fuels = ["NG"]
            """
        )
        assert config.new_technologies() == {}

    def test_technology_listed_under_both_end_uses_serves_both(self):
        config = _parse(
            """
            [end_uses."space cooling"]
            existing_fuels = ["ELC"]
            new_technologies = ["air-source heat pump", "rooftop air conditioner"]
            [end_uses."space heating"]
            existing_fuels = ["ELC"]
            new_technologies = ["gas furnace", "air-source heat pump"]
            """
        )
        assert config.new_technologies() == {
            NewTechnology.GasFurnace: [CommercialEndUse.SpaceHeating],
            NewTechnology.AirSourceHeatPump: [
                CommercialEndUse.SpaceHeating,
                CommercialEndUse.SpaceCooling,
            ],
            NewTechnology.RooftopAirConditioner: [CommercialEndUse.SpaceCooling],
        }

    def test_technology_that_cannot_serve_end_use_is_rejected(self):
        with pytest.raises(ValidationError, match="cannot serve space cooling"):
            _parse(
                """
                [end_uses."space cooling"]
                existing_fuels = ["ELC"]
                new_technologies = ["gas furnace"]
                """
            )

    def test_unknown_technology_is_rejected(self):
        with pytest.raises(ValidationError):
            _parse(
                """
                [end_uses."space heating"]
                existing_fuels = ["ELC"]
                new_technologies = ["heat pump"]
                """
            )

    def test_duplicate_technology_is_rejected(self):
        with pytest.raises(ValidationError, match="more than once"):
            _parse(
                """
                [end_uses."space heating"]
                existing_fuels = ["ELC"]
                new_technologies = ["gas furnace", "gas furnace"]
                """
            )


class TestTechnologyCatalog:
    def test_every_technology_has_a_spec(self):
        assert set(NEW_TECHNOLOGIES) == set(NewTechnology)

    def test_specs_only_serve_space_conditioning(self):
        for spec in NEW_TECHNOLOGIES.values():
            assert set(spec.aeo_technologies) <= {
                CommercialEndUse.SpaceHeating,
                CommercialEndUse.SpaceCooling,
            }

    def test_options_are_listed_in_config_docstring(self):
        docstring = " ".join((SpaceConditioningEndUseConfig.__doc__ or "").split())
        for technology in NewTechnology:
            assert f'"{technology.value}"' in docstring

    def test_options_are_listed_in_default_toml(self):
        toml = DEFAULT_CONFIG.read_text()
        for technology in NewTechnology:
            assert f'"{technology.value}"' in toml

    def test_default_toml_is_valid(self):
        end_uses = EndUsesConfig.model_validate(
            tomllib.loads(DEFAULT_CONFIG.read_text())["end_uses"]
        )
        assert NewTechnology.AirSourceHeatPump in end_uses.new_technologies()

import tomllib

import pytest
from canoe_schema.v4_0 import OperatorCode
from pydantic import ValidationError

from canoe.canoe_objects.fuel_serving_tech import FuelGrouping
from canoe.commercial.config import (
    CommercialEndUse,
    EndUsesConfig,
    ExistingStockEndUseConfig,
)
from canoe.common import CANOEFuel


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

    def test_existing_stock_only_includes_heating_and_cooling(self):
        config = _parse(
            """
            [end_uses."space cooling"]
            existing_fuels = ["ELC"]
            [end_uses.other]
            fuels = ["ELC"]
            """
        )
        existing = config.existing_stock()
        assert list(existing) == [CommercialEndUse.SpaceCooling]
        assert isinstance(
            existing[CommercialEndUse.SpaceCooling], ExistingStockEndUseConfig
        )
        assert existing[CommercialEndUse.SpaceCooling].existing_fuels == [
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

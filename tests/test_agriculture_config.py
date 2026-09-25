import tomllib
from pathlib import Path
from typing import Any

import pytest
from canoe_schema.v4_0 import OperatorCode
from pydantic import ValidationError

from canoe.agriculture.config import CANOEAgricultureConfig
from canoe.agriculture.input_splits import InputSplitStrategy
from canoe.common import CANOEFuel
from canoe.common.gdp import CERScenario, GDPProjectionPoint
from canoe.initializer import CANOEBaseConfig
from canoe.sector_config import resolve_sector_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"
DEFAULT_CONFIG = CONFIGURATION / "agriculture-default.toml"


@pytest.fixture
def base() -> CANOEBaseConfig:
    with (CONFIGURATION / "full-pipeline.toml").open("rb") as f:
        return CANOEBaseConfig.model_validate(tomllib.load(f)["compiler"]["base"])


def _config(base: CANOEBaseConfig, **overrides: Any) -> CANOEAgricultureConfig:
    with DEFAULT_CONFIG.open("rb") as f:
        raw = tomllib.load(f)
    return resolve_sector_config({**raw, **overrides}, base)


class TestDefaultConfig:
    def test_resolves_to_agriculture_with_inherited_fields(self, base: CANOEBaseConfig):
        config = resolve_sector_config(DEFAULT_CONFIG, base)
        assert isinstance(config, CANOEAgricultureConfig)
        assert config.data_version == base.data_version
        assert config.provinces == base.provinces
        assert config.gdp_scenario == CERScenario.GlobalNetZero
        assert config.gdp_projection_point == GDPProjectionPoint.PeriodEnd

    def test_defaults_reproduce_previous_module(self, base: CANOEBaseConfig):
        config = _config(base)
        assert config.fuels == [
            CANOEFuel.Electricity,
            CANOEFuel.NaturalGas,
            CANOEFuel.Diesel,
            CANOEFuel.Gasoline,
        ]
        assert (
            config.input_split_strategy == InputSplitStrategy.NRCanPercentWithRemainder
        )
        assert config.remainder_fuel == CANOEFuel.Diesel
        assert config.input_split_operator == OperatorCode.GE

    def test_sector_can_override_inherited_gdp_options(self, base: CANOEBaseConfig):
        config = _config(base, gdp_projection_point="legacy")
        assert config.gdp_projection_point == GDPProjectionPoint.Legacy


class TestFuels:
    def test_rejects_fuels_not_in_ceud_tables(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="not in the NRCan CEUD"):
            _config(base, fuels=["ELC", "H2"])

    def test_rejects_duplicate_fuels(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="more than once"):
            _config(base, fuels=["ELC", "ELC", "DSL"])

    def test_rejects_empty_fuels(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="at least one fuel"):
            _config(base, fuels=[])


class TestRemainderFuel:
    def test_must_be_a_modelled_fuel(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="must be one of fuels"):
            _config(base, fuels=["ELC", "NG"], remainder_fuel="DSL")

    def test_default_must_be_a_modelled_fuel(self, base: CANOEBaseConfig):
        with DEFAULT_CONFIG.open("rb") as f:
            raw = tomllib.load(f)
        del raw["remainder_fuel"]
        with pytest.raises(ValidationError, match="must be one of fuels"):
            resolve_sector_config({**raw, "fuels": ["ELC", "NG"]}, base)

    def test_not_allowed_with_normalized_strategy(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="does not apply"):
            _config(base, input_split_strategy="energy_normalized")

    def test_normalized_strategy_without_remainder_fuel(self, base: CANOEBaseConfig):
        with DEFAULT_CONFIG.open("rb") as f:
            raw = tomllib.load(f)
        del raw["remainder_fuel"]
        config = resolve_sector_config(
            {
                **raw,
                "fuels": ["ELC", "NG"],
                "input_split_strategy": "energy_normalized",
            },
            base,
        )
        assert config.input_split_strategy == InputSplitStrategy.EnergyNormalized

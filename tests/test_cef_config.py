import tomllib
from pathlib import Path
from typing import Any

import pytest
from canoe_schema.v4_0 import OperatorCode
from pydantic import ValidationError

from canoe.cef.config import CANOECEFConfig
from canoe.cef.energy_mix import SmallShareStrategy
from canoe.common import CANOESector
from canoe.common.projections import CERScenario, DemandProjectionPoint
from canoe.initializer import CANOEBaseConfig
from canoe.pipeline import CANOECompilerConfig
from canoe.sector_config import resolve_sector_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"
DEFAULT_CONFIG = CONFIGURATION / "cef-sectors" / "cef-default.toml"


@pytest.fixture
def base() -> CANOEBaseConfig:
    with (CONFIGURATION / "full-pipeline.toml").open("rb") as f:
        return CANOEBaseConfig.model_validate(tomllib.load(f)["compiler"]["base"])


def _config(base: CANOEBaseConfig, **overrides: Any) -> CANOECEFConfig:
    with DEFAULT_CONFIG.open("rb") as f:
        raw = tomllib.load(f)
    return resolve_sector_config({**raw, **overrides}, base)


class TestDefaultConfig:
    def test_resolves_to_cef_with_inherited_fields(self, base: CANOEBaseConfig):
        config = resolve_sector_config(DEFAULT_CONFIG, base)
        assert isinstance(config, CANOECEFConfig)
        assert config.data_version == base.data_version
        assert config.provinces == base.provinces
        assert config.future_periods == base.future_periods
        assert config.demand_projection_point == DemandProjectionPoint.PeriodEnd

    def test_defaults(self, base: CANOEBaseConfig):
        config = _config(base)
        assert config.sector == CANOESector.Transportation
        assert config.scenario == CERScenario.CurrentMeasures
        assert config.small_share_threshold == 0.02
        assert config.small_share_strategy == SmallShareStrategy.ZeroSmallShares
        assert config.input_split_operator == OperatorCode.LE

    @pytest.mark.parametrize(
        ("scenario", "code"),
        [
            ("Current Measures", "TRPCM003"),
            ("Canada Net-zero", "TRPCZ003"),
            ("Global Net-zero", "TRPGZ003"),
        ],
    )
    def test_dataset_code_follows_scenario(
        self, base: CANOEBaseConfig, scenario: str, code: str
    ):
        assert _config(base, scenario=scenario).get_dataset_code() == code

    def test_sector_by_name_or_code(self, base: CANOEBaseConfig):
        assert _config(base, sector="Industry").get_sector() == CANOESector.Industry
        assert _config(base, sector="COM").get_sector() == CANOESector.Commercial


class TestValidation:
    def test_scenario_is_required(self, base: CANOEBaseConfig):
        with DEFAULT_CONFIG.open("rb") as f:
            raw = tomllib.load(f)
        del raw["scenario"]
        with pytest.raises(ValidationError, match="scenario"):
            resolve_sector_config(raw, base)

    @pytest.mark.parametrize("sector", ["AGR", "ELC", "FUEL"])
    def test_rejects_sectors_cef_lacks(self, base: CANOEBaseConfig, sector: str):
        with pytest.raises(ValidationError, match="CEF has no"):
            _config(base, sector=sector)

    def test_rejects_legacy_projection_point(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="'legacy' does not apply"):
            _config(base, demand_projection_point="legacy")

    @pytest.mark.parametrize("threshold", [-0.1, 1.0])
    def test_rejects_threshold_out_of_range(
        self, base: CANOEBaseConfig, threshold: float
    ):
        with pytest.raises(ValidationError, match=r"must be in \[0, 1\)"):
            _config(base, small_share_threshold=threshold)

    def test_rejects_unknown_fields(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="Extra inputs"):
            _config(base, decimal_places=2)


class TestPipeline:
    def test_cef_sector_inline_table(self, base: CANOEBaseConfig):
        compiler = CANOECompilerConfig.model_validate(
            {
                "base": base,
                "sectors": {
                    "transportation": {
                        "module_name": "cef",
                        "sector": "TRP",
                        "scenario": "Global Net-zero",
                    }
                },
            }
        )
        assert isinstance(compiler.sectors["transportation"], CANOECEFConfig)

    def test_one_module_per_sector(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="more than one module per sector"):
            CANOECompilerConfig.model_validate(
                {
                    "base": base,
                    "sectors": {
                        "transportation": {
                            "module_name": "cef",
                            "sector": "TRP",
                            "scenario": "Global Net-zero",
                        },
                        "transportation_ghost": {
                            "module_name": "ghost",
                            "sector": "TRP",
                            "fuels": ["ELC"],
                        },
                    },
                }
            )

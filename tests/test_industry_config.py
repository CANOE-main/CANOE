import tomllib
from pathlib import Path
from typing import Any

import pytest
from canoe_schema.v4_0 import OperatorCode
from pydantic import ValidationError

from canoe.common import CANOEFuel
from canoe.common.gdp import CERScenario, GDPProjectionPoint
from canoe.industry.config import (
    SUPPORTED_FUELS,
    CANOEIndustryConfig,
    OtherFuelsTreatment,
)
from canoe.industry.subsectors import IndustrySubsector
from canoe.initializer import CANOEBaseConfig
from canoe.sector_config import resolve_sector_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"
DEFAULT_CONFIG = CONFIGURATION / "industry-default.toml"


@pytest.fixture
def base() -> CANOEBaseConfig:
    with (CONFIGURATION / "full-pipeline.toml").open("rb") as f:
        return CANOEBaseConfig.model_validate(tomllib.load(f)["compiler"]["base"])


def _config(base: CANOEBaseConfig, **overrides: Any) -> CANOEIndustryConfig:
    with DEFAULT_CONFIG.open("rb") as f:
        raw = tomllib.load(f)
    return resolve_sector_config({**raw, **overrides}, base)


class TestDefaultConfig:
    def test_resolves_to_industry_with_inherited_fields(self, base: CANOEBaseConfig):
        config = resolve_sector_config(DEFAULT_CONFIG, base)
        assert isinstance(config, CANOEIndustryConfig)
        assert config.data_version == base.data_version
        assert config.provinces == base.provinces
        assert config.gdp_scenario == CERScenario.GlobalNetZero
        assert config.gdp_projection_point == GDPProjectionPoint.PeriodEnd
        assert config.get_dataset_code() == f"INDHR{base.data_version}"

    def test_every_subsector_modelled_with_every_fuel_but_other(
        self, base: CANOEBaseConfig
    ):
        config = _config(base)
        assert config.modelled_subsectors() == list(IndustrySubsector)
        for subsector in IndustrySubsector:
            assert config.fuels_of(subsector) == list(SUPPORTED_FUELS)
        assert config.other_fuels == OtherFuelsTreatment.Deduct
        assert config.input_split_operator == OperatorCode.GE

    def test_keeps_previous_technology_names(self):
        assert [s.short_desc() for s in IndustrySubsector] == [
            "CON",
            "PULP",
            "SMELT",
            "REFINING",
            "CEMENT",
            "CHEM",
            "STEEL",
            "OTH_MAN",
            "FOR",
            "MINING",
        ]


class TestFuels:
    def test_rejects_fuels_not_in_ceud_tables(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="not in the NRCan CEUD"):
            _config(base, fuels=["ELC", "GSL"])

    def test_rejects_duplicate_fuels(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="more than once"):
            _config(base, fuels=["ELC", "ELC", "NG"])

    def test_rejects_empty_fuels(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="at least one fuel"):
            _config(base, fuels=[])

    def test_rejects_other_in_fuels(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="other_fuels"):
            _config(base, fuels=["ELC", "OTH"])
        with pytest.raises(ValidationError, match="other_fuels"):
            _config(base, subsectors={"cement": {"fuels": ["ELC", "OTH"]}})


class TestOtherFuels:
    @pytest.mark.parametrize("value", ["deduct", "free"])
    def test_options(self, base: CANOEBaseConfig, value: str):
        assert _config(base, other_fuels=value).other_fuels == value

    def test_rejects_unknown_option(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError):
            _config(base, other_fuels="spread")


class TestSubsectors:
    def test_skip_leaves_the_subsector_out(self, base: CANOEBaseConfig):
        config = _config(
            base, subsectors={"construction": {"skip": True}, "mining": {"skip": True}}
        )
        modelled = config.modelled_subsectors()
        assert IndustrySubsector.Construction not in modelled
        assert IndustrySubsector.Mining not in modelled
        assert len(modelled) == len(IndustrySubsector) - 2

    def test_fuels_override_only_that_subsector(self, base: CANOEBaseConfig):
        config = _config(
            base, subsectors={"pulp and paper": {"fuels": ["WOOD", "ELC"]}}
        )
        assert config.fuels_of(IndustrySubsector.PulpAndPaper) == [
            CANOEFuel.Wood,
            CANOEFuel.Electricity,
        ]
        assert config.fuels_of(IndustrySubsector.Cement) == config.fuels

    def test_subsector_fuels_are_checked(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="not in the NRCan CEUD"):
            _config(base, subsectors={"cement": {"fuels": ["H2"]}})
        with pytest.raises(ValidationError, match="at least one fuel"):
            _config(base, subsectors={"cement": {"fuels": []}})

    def test_rejects_fuels_on_skipped_subsector(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="skipped subsector"):
            _config(base, subsectors={"cement": {"skip": True, "fuels": ["ELC"]}})

    def test_rejects_unknown_subsector(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError):
            _config(base, subsectors={"steel": {"skip": True}})

    def test_rejects_unknown_subsector_option(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError):
            _config(base, subsectors={"cement": {"remainder_fuel": "NG"}})

    def test_rejects_skipping_every_subsector(self, base: CANOEBaseConfig):
        with pytest.raises(ValidationError, match="every industry subsector"):
            _config(
                base, subsectors={s.value: {"skip": True} for s in IndustrySubsector}
            )

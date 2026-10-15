import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from canoe.electricity.catalogue import (
    CCSRetrofit,
    GenerationTechnology,
    StorageTechnology,
)
from canoe.electricity.config import CANOEElectricityConfig
from canoe.initializer import CANOEBaseConfig
from canoe.pipeline import CANOECompilerConfig

CONFIGURATION = Path(__file__).parents[1] / "configuration"
PIPELINE_CONFIG = CONFIGURATION / "full-pipeline.toml"
ELECTRICITY_CONFIG = CONFIGURATION / "electricity-default.toml"


@pytest.fixture
def compiler_raw() -> dict[str, Any]:
    with PIPELINE_CONFIG.open("rb") as f:
        return tomllib.load(f)["compiler"]


@pytest.fixture
def base(compiler_raw: dict[str, Any]) -> CANOEBaseConfig:
    return CANOEBaseConfig.model_validate(compiler_raw["base"])


@pytest.fixture
def electricity_raw() -> dict[str, Any]:
    with ELECTRICITY_CONFIG.open("rb") as f:
        return tomllib.load(f)


def _config(
    electricity_raw: dict[str, Any], base: CANOEBaseConfig, **overrides: Any
) -> CANOEElectricityConfig:
    return CANOEElectricityConfig.model_validate(
        {**electricity_raw, **overrides}, context={"base": base}
    )


class TestPipelineConfig:
    def test_resolves_toml_path_with_inherited_fields(
        self,
        compiler_raw: dict[str, Any],
        base: CANOEBaseConfig,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # The pipeline TOML gives the path relative to the project root
        monkeypatch.chdir(CONFIGURATION.parent)
        compiler = CANOECompilerConfig.model_validate({**compiler_raw, "sectors": {}})
        assert compiler.electricity is not None
        assert compiler.electricity.data_version == base.data_version
        assert compiler.electricity.provinces == base.provinces
        assert compiler.electricity.future_periods == base.future_periods
        assert compiler.electricity.database_file == base.db_output_dir
        assert compiler.electricity.model_currency_year == base.model_currency_year

    def test_electricity_is_optional(self, compiler_raw: dict[str, Any]):
        raw = {
            key: value for key, value in compiler_raw.items() if key != "electricity"
        }
        compiler = CANOECompilerConfig.model_validate({**raw, "sectors": {}})
        assert compiler.electricity is None


class TestDefaults:
    def test_default_toml_models_everything_but_the_exogenous_demand(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        config = _config(electricity_raw, base)
        assert not config.exogenous_demand
        assert not config.generation.skip_existing
        assert config.generation.new_technologies
        assert config.generation.ccs_retrofits == list(CCSRetrofit)
        assert not config.storage.skip_existing
        assert config.storage.new_technologies
        assert not config.trade.skip_endogenous
        assert not config.trade.skip_boundary
        assert not config.reliability.skip
        assert config.get_dataset_code() == f"ELCHR{base.data_version}"

    def test_atb_currency_year_is_correct_by_default(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        source_years = {
            k: v
            for k, v in electricity_raw["source_years"].items()
            if k != "atb_currency"
        }
        config = _config(electricity_raw, base, source_years=source_years)
        assert config.source_years.atb_currency == 2022

    def test_empty_lists_build_nothing_new(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        generation = {"new_technologies": [], "ccs_retrofits": []}
        storage = {"new_technologies": []}
        config = _config(electricity_raw, base, generation=generation, storage=storage)
        assert config.generation.new_technologies == []
        assert config.generation.ccs_retrofits == []
        assert config.storage.new_technologies == []


class TestValidation:
    def test_rejects_unknown_fields(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        with pytest.raises(ValidationError, match="Extra inputs"):
            _config(electricity_raw, base, include_imports=True)

    def test_source_years_are_required(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        raw = {k: v for k, v in electricity_raw.items() if k != "source_years"}
        with pytest.raises(ValidationError, match="source_years"):
            _config(raw, base)

    @pytest.mark.parametrize(
        ("table", "field"),
        [
            ("generation", "new_technologies"),
            ("generation", "ccs_retrofits"),
            ("storage", "new_technologies"),
        ],
    )
    def test_technology_lists_are_required(
        self,
        electricity_raw: dict[str, Any],
        base: CANOEBaseConfig,
        table: str,
        field: str,
    ):
        # No defaults in the code: the TOML says what is built
        options = {k: v for k, v in electricity_raw[table].items() if k != field}
        with pytest.raises(ValidationError, match=field):
            _config(electricity_raw, base, **{table: options})

    def test_rejects_unknown_technology(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        generation = {**electricity_raw["generation"], "new_technologies": ["fusion"]}
        with pytest.raises(ValidationError, match="fusion"):
            _config(electricity_raw, base, generation=generation)

    def test_rejects_duplicate_technologies(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        storage = {"new_technologies": ["battery_2h", "battery_2h"]}
        with pytest.raises(ValidationError, match="more than once"):
            _config(electricity_raw, base, storage=storage)

    def test_retrofit_needs_its_generator(
        self, electricity_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        # Without existing generators, a natural gas retrofit needs new ng_cc
        generation: dict[str, Any] = {
            "skip_existing": True,
            "new_technologies": ["ng_ct"],
            "ccs_retrofits": ["ng_ccs_retrofit_90"],
        }
        with pytest.raises(ValidationError, match="ng_ccs_retrofit_90"):
            _config(electricity_raw, base, generation=generation)

        generation["new_technologies"] = ["ng_cc"]
        config = _config(electricity_raw, base, generation=generation)
        assert config.generation.ccs_retrofits == [CCSRetrofit.NaturalGasCC90]


class TestCatalogue:
    @pytest.mark.parametrize(
        "enum", [GenerationTechnology, StorageTechnology, CCSRetrofit]
    )
    def test_technology_codes_are_unique(
        self,
        enum: type[GenerationTechnology] | type[StorageTechnology] | type[CCSRetrofit],
    ):
        codes = [member.get_tech_code() for member in enum]
        assert len(set(codes)) == len(codes)

    def test_every_member_has_its_attributes(self):
        # The lookup tables of the methods cover every member
        for technology in GenerationTechnology:
            technology.get_input_fuel()
            technology.get_grid_level()
        for storage in StorageTechnology:
            assert storage.get_duration_hours() > 0
        for retrofit in CCSRetrofit:
            assert retrofit.get_generator().get_input_fuel() is not None

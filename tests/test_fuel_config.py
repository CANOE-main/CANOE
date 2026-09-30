import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from canoe.common.periods import ProjectionPoint
from canoe.fuel.config import CANOEFuelConfig
from canoe.initializer import CANOEBaseConfig
from canoe.pipeline import CANOECompilerConfig

PIPELINE_CONFIG = Path(__file__).parents[1] / "configuration" / "full-pipeline.toml"


@pytest.fixture
def compiler_raw() -> dict[str, Any]:
    with PIPELINE_CONFIG.open("rb") as f:
        return tomllib.load(f)["compiler"]


@pytest.fixture
def base(compiler_raw: dict[str, Any]) -> CANOEBaseConfig:
    return CANOEBaseConfig.model_validate(compiler_raw["base"])


def _config(
    compiler_raw: dict[str, Any], base: CANOEBaseConfig, **overrides: Any
) -> CANOEFuelConfig:
    return CANOEFuelConfig.model_validate(
        {**compiler_raw["fuel"], **overrides}, context={"base": base}
    )


class TestPipelineConfig:
    def test_resolves_inline_table_with_inherited_fields(
        self, compiler_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        compiler = CANOECompilerConfig.model_validate({**compiler_raw, "sectors": {}})
        assert compiler.fuel is not None
        assert compiler.fuel.data_version == base.data_version
        assert compiler.fuel.provinces == base.provinces
        assert compiler.fuel.future_periods == base.future_periods
        assert compiler.fuel.database_file == base.db_output_dir
        assert compiler.fuel.price_projection_point == ProjectionPoint.PeriodEnd
        assert compiler.fuel.model_currency_year == base.model_currency_year

    def test_fuel_is_optional(self, compiler_raw: dict[str, Any]):
        raw = {key: value for key, value in compiler_raw.items() if key != "fuel"}
        compiler = CANOECompilerConfig.model_validate({**raw, "sectors": {}})
        assert compiler.fuel is None


class TestDefaults:
    def test_previous_errors_fixed_by_default(self, base: CANOEBaseConfig):
        config = CANOEFuelConfig.model_validate({}, context={"base": base})
        assert not config.reproduce_previous_price_errors
        assert not config.reproduce_previous_emission_errors

    def test_can_override_inherited_price_options(
        self, compiler_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        config = _config(
            compiler_raw,
            base,
            price_projection_point="period_start",
            model_currency_year=2022,
            reproduce_previous_price_errors=False,
        )
        assert config.price_projection_point == ProjectionPoint.PeriodStart
        assert config.model_currency_year == 2022


class TestValidation:
    def test_rejects_unknown_fields(
        self, compiler_raw: dict[str, Any], base: CANOEBaseConfig
    ):
        with pytest.raises(ValidationError, match="Extra inputs"):
            _config(compiler_raw, base, fuels=["NG"])

    def test_needs_base_for_inherited_fields(self, compiler_raw: dict[str, Any]):
        with pytest.raises(ValidationError, match="mandatory fields missing"):
            CANOEFuelConfig.model_validate(compiler_raw["fuel"])


def test_previous_price_errors_need_2020_dollars(
    compiler_raw: dict[str, Any], base: CANOEBaseConfig
):
    with pytest.raises(ValidationError, match="model_currency_year = 2020"):
        _config(
            compiler_raw,
            base,
            reproduce_previous_price_errors=True,
            model_currency_year=2022,
        )

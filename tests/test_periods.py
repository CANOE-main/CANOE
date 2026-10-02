import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from canoe.initializer import CANOEBaseConfig

PIPELINE_CONFIG = Path(__file__).parents[1] / "configuration" / "full-pipeline.toml"


@pytest.fixture
def base_raw() -> dict[str, Any]:
    with PIPELINE_CONFIG.open("rb") as f:
        return tomllib.load(f)["compiler"]["base"]


def test_end_of_horizon_follows_last_model_period(base_raw: dict[str, Any]):
    base = CANOEBaseConfig.model_validate(
        {**base_raw, "future_periods": [2025, 2030, 2045]}
    )
    assert base.period_step == 5
    assert base.end_of_horizon == 2050


def test_period_step_is_configurable(base_raw: dict[str, Any]):
    base = CANOEBaseConfig.model_validate(
        {**base_raw, "future_periods": [2025, 2035], "period_step": 10}
    )
    assert base.end_of_horizon == 2045


@pytest.mark.parametrize("future_periods", [[], [2030, 2025], [2025, 2025]])
def test_rejects_invalid_future_periods(
    base_raw: dict[str, Any], future_periods: list[int]
):
    with pytest.raises(ValidationError, match="future_periods"):
        CANOEBaseConfig.model_validate({**base_raw, "future_periods": future_periods})


@pytest.mark.parametrize("period_step", [0, -5])
def test_rejects_non_positive_period_step(base_raw: dict[str, Any], period_step: int):
    with pytest.raises(ValidationError, match="period_step must be positive"):
        CANOEBaseConfig.model_validate({**base_raw, "period_step": period_step})

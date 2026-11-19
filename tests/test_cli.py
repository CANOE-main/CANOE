from pathlib import Path

import pytest
from loguru import logger
from typer.testing import CliRunner

from canoe import cli
from canoe.cli import app
from canoe.pipeline import CANOECompilerConfig

CONFIGURATION = Path(__file__).parents[1] / "configuration"


def _invoke(*args: str):
    return CliRunner().invoke(app, list(args))


def test_no_arguments_shows_the_commands():
    result = _invoke()
    assert "run" in result.output
    assert "compile" in result.output
    assert "check" in result.output


def test_version():
    result = _invoke("--version")
    assert result.exit_code == 0
    assert result.output.startswith("canoe ")


def test_check_accepts_the_repository_configuration():
    result = _invoke("check", str(CONFIGURATION / "full-pipeline.toml"))
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_check_show_prints_the_resolved_configuration():
    result = _invoke("check", "--show", str(CONFIGURATION / "full-pipeline.toml"))
    assert result.exit_code == 0, result.output
    # Paths are resolved from the TOML's folder
    assert str(Path("canoe-pwd") / "canoe.sqlite") in result.output
    assert "configuration/../" not in result.output


def test_compile_runs_only_the_compiler(monkeypatch: pytest.MonkeyPatch):
    compiled: list[CANOECompilerConfig] = []
    monkeypatch.setattr(cli, "run_compiler", compiled.append)
    monkeypatch.setattr(cli, "run", lambda _: pytest.fail("ran the whole pipeline"))
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="INFO")
    try:
        result = _invoke("compile", str(CONFIGURATION / "full-pipeline.toml"))
    finally:
        logger.remove(sink)
    assert result.exit_code == 0, result.output
    assert len(compiled) == 1
    # full-pipeline.toml configures both
    assert any("ignoring [representative_periods_config]" in m for m in messages)
    assert any("ignoring [temoa_config]" in m for m in messages)


def test_compile_needs_a_compiler(tmp_path: Path):
    pipeline = tmp_path / "pipeline.toml"
    pipeline.write_text('input_database = "canoe.sqlite"\n')
    result = _invoke("compile", str(pipeline))
    assert result.exit_code == 1
    assert "nothing to compile" in result.output


def test_missing_config_is_a_usage_error(tmp_path: Path):
    result = _invoke("run", str(tmp_path / "missing.toml"))
    assert result.exit_code == 2


def test_missing_sector_toml_is_reported(tmp_path: Path):
    pipeline = tmp_path / "pipeline.toml"
    pipeline.write_text(
        (CONFIGURATION / "full-pipeline.toml")
        .read_text()
        .replace('"commercial-default.toml"', '"sectors/missing.toml"')
    )
    result = _invoke("check", str(pipeline))
    assert result.exit_code == 1
    assert "File not found" in result.output
    assert "missing.toml" in result.output


def test_invalid_toml_is_reported(tmp_path: Path):
    pipeline = tmp_path / "pipeline.toml"
    pipeline.write_text("[compiler.base\n")
    result = _invoke("check", str(pipeline))
    assert result.exit_code == 1
    assert "Invalid TOML" in result.output


def test_invalid_setting_is_reported(tmp_path: Path):
    pipeline = tmp_path / "pipeline.toml"
    pipeline.write_text('input_database = "canoe.sqlite"\n[temoa_config]\nsolver = 1\n')
    result = _invoke("check", str(pipeline))
    assert result.exit_code == 1
    assert "Invalid configuration" in result.output
    assert "temoa_config" in result.output

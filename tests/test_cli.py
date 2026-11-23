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


def _pipeline_with_cache(folder: Path) -> Path:
    """A pipeline TOML in `folder` with no modules, reading the cache `folder/cache`."""
    pipeline = folder / "pipeline.toml"
    pipeline.write_text(
        """
[compiler.base]
db_output_dir = "canoe.sqlite"
data_version = "003"
existing_periods = [2020]
future_periods = [2025]
period_step = 5
provinces = ["ON"]
global_discount_rate = 0.03

[compiler.base.data_cache_config]
cache_dir = "cache"
cache_date = "2026-08-10"
"""
    )
    return pipeline


def _install_fake_cache(cache: Path) -> None:
    (cache / "silver" / "2026-08-10").mkdir(parents=True)
    (cache / "renewables").mkdir()
    (cache / "renewables" / "cost_fixed.parquet").write_bytes(b"x")


def test_compile_runs_only_the_compiler(monkeypatch: pytest.MonkeyPatch):
    compiled: list[CANOECompilerConfig] = []
    monkeypatch.setattr(cli, "run_compiler", compiled.append)
    monkeypatch.setattr(cli, "run", lambda _: pytest.fail("ran the whole pipeline"))
    # The repository's cache may not be installed where the tests run
    monkeypatch.setattr(cli, "_missing_cache", lambda _: None)
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


@pytest.mark.parametrize("command", ["run", "compile"])
def test_running_without_the_cache_stops_before_starting(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli, "run_compiler", lambda _: pytest.fail("compiled"))
    monkeypatch.setattr(cli, "run", lambda _: pytest.fail("ran"))
    result = _invoke(command, str(_pipeline_with_cache(tmp_path)))
    assert result.exit_code == 1
    assert "lacks the 2026-08-10 snapshot and the renewables" in result.output
    assert f"canoe cache install {tmp_path / 'cache'}" in result.output


def test_running_with_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    compiled: list[CANOECompilerConfig] = []
    monkeypatch.setattr(cli, "run_compiler", compiled.append)
    _install_fake_cache(tmp_path / "cache")
    result = _invoke("compile", str(_pipeline_with_cache(tmp_path)))
    assert result.exit_code == 0, result.output
    assert len(compiled) == 1


def test_check_warns_about_a_missing_cache(tmp_path: Path):
    result = _invoke("check", str(_pipeline_with_cache(tmp_path)))
    assert result.exit_code == 0, result.output
    assert "valid" in result.output
    assert "lacks the 2026-08-10 snapshot" in result.output


def test_cache_status(tmp_path: Path):
    cache = tmp_path / "cache"
    result = _invoke("cache", "status", str(cache))
    assert result.exit_code == 0
    assert "no cache" in result.output

    _install_fake_cache(cache)
    result = _invoke("cache", "status", str(cache), "--date", "2026-08-10")
    assert result.exit_code == 0, result.output
    assert "snapshots 2026-08-10; renewables yes" in result.output

    result = _invoke("cache", "status", str(cache), "--date", "2026-09-01")
    assert result.exit_code == 1
    assert "Not usable for 2026-09-01" in result.output


def test_cache_install_asks_for_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    installed: list[Path] = []

    def fake_install(cache_dir: Path) -> cli.CacheContents:
        installed.append(cache_dir)
        _install_fake_cache(cache_dir)
        return cli.cache_contents(cache_dir)

    monkeypatch.setattr(cli, "install_cache", fake_install)
    result = CliRunner().invoke(app, ["cache", "install"], input=f"{tmp_path / 'c'}\n")
    assert result.exit_code == 0, result.output
    assert "Folder of the CANOE data cache [.cache]" in result.output
    assert installed == [tmp_path / "c"]
    assert "Installed" in result.output


def test_cache_install_defaults_to_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    installed: list[Path] = []
    monkeypatch.setattr(
        cli, "install_cache", lambda d: installed.append(d) or cli.cache_contents(d)
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["cache", "install"], input="\n")
    assert result.exit_code == 0, result.output
    assert installed == [Path(".cache")]


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

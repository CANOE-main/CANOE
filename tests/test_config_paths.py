"""
Relative paths in configuration TOMLs resolve from the folder of the TOML they are
written in (`canoe.common.config_paths`).
"""

import shutil
from pathlib import Path

import pytest

from canoe.common.projections import CSVSeriesSource
from canoe.pipeline import load_pipeline_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"


def _write_scenario(
    root: Path,
    base_gdp: str = '{ source = "cer", scenario = "Global Net-zero" }',
    commercial_gdp: str | None = None,
) -> Path:
    """
    A scenario folder like the ones of `canoe init`: `<root>/config/scenario/` with
    the pipeline TOML and the module TOMLs in `sectors/`. Returns the pipeline TOML.
    """
    scenario = root / "config" / "scenario"
    sectors = scenario / "sectors"
    sectors.mkdir(parents=True)
    commercial = (CONFIGURATION / "commercial-default.toml").read_text()
    if commercial_gdp is not None:
        # Top-level keys go before the first table
        commercial = f"gdp = {commercial_gdp}\n{commercial}"
    (sectors / "commercial.toml").write_text(commercial)
    shutil.copy(
        CONFIGURATION / "electricity-default.toml", sectors / "electricity.toml"
    )
    pipeline = scenario / "full-pipeline.toml"
    pipeline.write_text(
        f"""
[compiler.base]
db_output_dir = "../../canoe-pwd/canoe.sqlite"
data_version = "003"
existing_periods = [2020, 2022, 2024]
future_periods = [2025, 2030]
period_step = 5
provinces = ["ON"]
global_discount_rate = 0.03
gdp = {base_gdp}
population = {{ source = "statcan" }}

[compiler.base.data_cache_config]
cache_dir = "../../.cache"
cache_date = "2026-08-10"

[compiler.sectors]
commercial = "sectors/commercial.toml"

[compiler.electricity]
config_file = "sectors/electricity.toml"

[representative_periods_config]
[representative_periods_config.clustering]
kind = "tsam"
data_dir = "timeseries"
weather_year = 2018
n_periods = 4

[temoa_config]
solver = "appsi_highs"
scenario_mode = "build_only"
output_path = "../../temoa-outputs"
"""
    )
    return pipeline


class TestLoadPipelineConfig:
    def test_paths_resolve_from_the_pipeline_toml_folder(self, tmp_path: Path):
        pipeline = _write_scenario(tmp_path)
        scenario = pipeline.parent
        config = load_pipeline_config(pipeline)

        assert config.compiler is not None
        base = config.compiler.base
        assert base.db_output_dir == tmp_path / "canoe-pwd/canoe.sqlite"
        assert base.data_cache_config.cache_dir == tmp_path / ".cache"
        assert config.representative_periods_config is not None
        assert config.representative_periods_config.clustering.data_dir == (  # pyright: ignore[reportAttributeAccessIssue]
            scenario / "timeseries"
        )
        assert config.temoa_config is not None
        assert config.temoa_config.output_path == tmp_path / "temoa-outputs"

    def test_modules_inherit_the_resolved_paths(self, tmp_path: Path):
        config = load_pipeline_config(_write_scenario(tmp_path))
        assert config.compiler is not None
        base = config.compiler.base
        assert config.compiler.electricity is not None
        assert config.compiler.electricity.database_file == base.db_output_dir
        commercial = config.compiler.sectors["commercial"]
        assert commercial.database_file == base.db_output_dir
        assert commercial.data_cache_config == base.data_cache_config  # pyright: ignore[reportAttributeAccessIssue]

    def test_inherited_csv_path_is_not_joined_again(self, tmp_path: Path):
        # The sector TOML sits in sectors/, but the path came from the pipeline TOML
        pipeline = _write_scenario(
            tmp_path, base_gdp='{ source = "csv", path = "gdp.csv" }'
        )
        config = load_pipeline_config(pipeline)
        assert config.compiler is not None
        expected = CSVSeriesSource(path=pipeline.parent / "gdp.csv")
        assert config.compiler.base.gdp == expected
        assert config.compiler.sectors["commercial"].gdp == expected  # pyright: ignore[reportAttributeAccessIssue]

    def test_paths_in_a_sector_toml_resolve_from_its_folder(self, tmp_path: Path):
        pipeline = _write_scenario(
            tmp_path, commercial_gdp='{ source = "csv", path = "gdp.csv" }'
        )
        config = load_pipeline_config(pipeline)
        assert config.compiler is not None
        assert config.compiler.sectors["commercial"].gdp == CSVSeriesSource(  # pyright: ignore[reportAttributeAccessIssue]
            path=pipeline.parent / "sectors" / "gdp.csv"
        )

    def test_absolute_paths_are_kept(self, tmp_path: Path):
        database = tmp_path / "elsewhere" / "canoe.sqlite"
        pipeline = _write_scenario(tmp_path)
        pipeline.write_text(
            pipeline.read_text().replace(
                '"../../canoe-pwd/canoe.sqlite"', f'"{database.as_posix()}"'
            )
        )
        config = load_pipeline_config(pipeline)
        assert config.compiler is not None
        assert config.compiler.base.db_output_dir == database

    def test_the_folder_it_runs_from_does_not_matter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pipeline = _write_scenario(tmp_path)
        databases: list[Path] = []
        for cwd, relative in [
            (pipeline.parent, "full-pipeline.toml"),
            (tmp_path, "config/scenario/full-pipeline.toml"),
        ]:
            monkeypatch.chdir(cwd)
            config = load_pipeline_config(Path(relative))
            assert config.compiler is not None
            # Resolved while in `cwd`: relative paths are relative to it
            databases.append(config.compiler.base.db_output_dir.resolve())
        assert databases == [(tmp_path / "canoe-pwd/canoe.sqlite").resolve()] * 2

    def test_defaults_stay_relative_to_where_it_runs(self, tmp_path: Path):
        # working_directory is not set in the TOML
        config = load_pipeline_config(_write_scenario(tmp_path))
        assert config.working_directory == Path("./canoe-pwd")

    def test_the_repository_configurations_load(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # From any folder: their paths are relative to configuration/
        monkeypatch.chdir(tmp_path)
        for pipeline in [
            CONFIGURATION / "full-pipeline.toml",
            CONFIGURATION / "reproduce-all-high" / "pipeline.toml",
            CONFIGURATION / "temoa-pipeline.toml",
        ]:
            load_pipeline_config(pipeline)

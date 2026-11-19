"""
`canoe init`: the template renders into a project whose configuration validates.
"""

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from canoe import cli
from canoe.cli import app
from canoe.pipeline import load_pipeline_config
from canoe.project_init import create_project, template_dir

CONFIGURATION = Path(__file__).parents[1] / "configuration"


def test_default_project_validates(tmp_path: Path):
    project = tmp_path / "my-study"
    pipeline = create_project(project, cache_dir=None, defaults=True)
    assert pipeline == project / "config" / "all-high" / "full-pipeline.toml"

    config = load_pipeline_config(pipeline)
    assert config.compiler is not None
    assert set(config.compiler.sectors) == {
        "agriculture",
        "commercial",
        "industry",
        "residential",
    }
    assert config.compiler.electricity is not None
    assert config.compiler.fuel is not None
    assert len(config.compiler.base.provinces) == 10
    # Everything the pipeline writes or reads stays in the project
    assert config.compiler.base.data_cache_config.cache_dir == project / ".cache"
    assert config.working_directory == project / "canoe-pwd" / "all-high"
    assert config.db_path == project / "canoe-pwd" / "all-high" / "canoe.sqlite"
    assert config.temoa_config is not None
    assert config.temoa_config.output_path == project / "temoa-outputs" / "all-high"


def test_project_files(tmp_path: Path):
    project = tmp_path / "my-study"
    create_project(project, cache_dir=None, defaults=True)
    for name in [
        "main.py",
        "README.md",
        "pyproject.toml",
        ".gitignore",
        ".python-version",
        ".copier-answers.yml",
    ]:
        assert (project / name).is_file(), name

    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == "my-study"
    assert pyproject["project"]["dependencies"] == ["canoe[solvers]"]
    assert "canoe" in pyproject["tool"]["uv"]["sources"]
    compile(
        (project / "main.py").read_text(), "main.py", "exec"
    )  # valid Python after rendering


def test_answers(tmp_path: Path):
    project = tmp_path / "study"
    cache = tmp_path / "shared cache"
    pipeline = create_project(
        project,
        cache_dir=cache,
        defaults=True,
        answers={
            "project_name": "Hydrogen Study",
            "description": 'Hydrogen in "Quebec"',
            "provinces": ["ON", "QC"],
        },
    )
    config = load_pipeline_config(pipeline)
    assert config.compiler is not None
    assert [p.name for p in config.compiler.base.provinces] == ["ONTARIO", "QUEBEC"]
    assert config.compiler.base.data_cache_config.cache_dir == cache.resolve()

    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == "hydrogen-study"
    assert pyproject["project"]["description"] == 'Hydrogen in "Quebec"'
    assert 'Hydrogen in "Quebec"' in (project / "README.md").read_text()


@pytest.mark.parametrize(
    "sector", ["agriculture", "commercial", "industry", "residential", "electricity"]
)
def test_sector_tomls_are_the_repository_defaults(sector: str):
    # The template's copies must follow configuration/*-default.toml
    scenario = next((template_dir() / "template" / "config").iterdir())
    template = scenario / "sectors" / f"{sector}.toml"
    default = CONFIGURATION / f"{sector}-default.toml"
    assert template.read_text() == default.read_text()


class TestInitCommand:
    def test_defaults(self, tmp_path: Path):
        project = tmp_path / "study"
        result = CliRunner().invoke(app, ["init", str(project), "--defaults"])
        assert result.exit_code == 0, result.output
        assert "Created" in result.output
        # No cache asked for nor installed with --defaults
        assert f"canoe cache install {project / '.cache'}" in result.output
        assert (project / "main.py").is_file()

    def test_refuses_a_folder_with_files(self, tmp_path: Path):
        (tmp_path / "notes.txt").write_text("mine")
        result = CliRunner().invoke(app, ["init", str(tmp_path), "--defaults"])
        assert result.exit_code == 1
        assert "not empty" in result.output

    def test_asks_for_the_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Copier's own questions need a terminal: take their defaults
        monkeypatch.setattr(
            cli,
            "create_project",
            lambda project_dir, cache_dir, defaults: create_project(
                project_dir, cache_dir, defaults=True
            ),
        )
        cache = tmp_path / "cache"
        (cache / "silver" / "2026-08-10").mkdir(parents=True)
        (cache / "renewables").mkdir()
        (cache / "renewables" / "cost_fixed.parquet").write_bytes(b"x")
        project = tmp_path / "study"
        result = CliRunner().invoke(app, ["init", str(project)], input=f"{cache}\n")
        assert result.exit_code == 0, result.output
        config = load_pipeline_config(project / "config/all-high/full-pipeline.toml")
        assert config.compiler is not None
        assert config.compiler.base.data_cache_config.cache_dir == cache.resolve()
        # The cache has the snapshot: nothing to install
        assert "Install" not in result.output

    def test_offers_to_install_the_cache_in_the_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            cli,
            "create_project",
            lambda project_dir, cache_dir, defaults: create_project(
                project_dir, cache_dir, defaults=True
            ),
        )
        installed: list[Path] = []
        monkeypatch.setattr(
            cli, "install_cache", lambda d: installed.append(d) or cli.cache_contents(d)
        )
        project = tmp_path / "study"
        # Empty cache answer (inside the project), then yes to installing
        result = CliRunner().invoke(app, ["init", str(project)], input="\ny\n")
        assert result.exit_code == 0, result.output
        assert installed == [project / ".cache"]

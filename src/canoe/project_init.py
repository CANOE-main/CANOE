"""
Create a CANOE project from the template in `canoe/project_template` (`canoe init`).

The template is a Copier template shipped inside canoe, so a project is created with
the configuration files of the canoe that creates it: the TOMLs always validate
against the models of the canoe the project depends on. Copier asks the questions of
`copier.yml` (name, description, scenario, provinces); `canoe init` adds what it
knows better than the user:

- `canoe_source`: where the project installs canoe from, the canoe running `init`
  (a git commit, or the local checkout during development);
- `cache_dir`: the data cache the user named, or `.cache` inside the project.

`copier update` is not offered yet: it needs the template fetched from a tagged git
repository, not from an installed package.
"""

import json
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from copier import run_copy


def template_dir() -> Path:
    """The Copier template shipped with canoe."""
    return Path(str(files("canoe").joinpath("project_template")))


def canoe_source() -> str:
    """
    Where a new project installs canoe from, as the TOML inline table of
    `[tool.uv.sources] canoe`: the commit canoe was installed from (`uvx --from
    git+...`), the local checkout it runs from (development), or the repository's
    default branch when neither is known.
    """
    raw = distribution("canoe").read_text("direct_url.json")
    if raw:
        info: dict[str, Any] = json.loads(raw)
        if "vcs_info" in info:
            url = json.dumps(info["url"])
            commit = json.dumps(info["vcs_info"]["commit_id"])
            return f"{{ git = {url}, rev = {commit} }}"
        if "dir_info" in info:
            path = Path(url2pathname(urlparse(info["url"]).path))
            editable = "true" if info["dir_info"].get("editable") else "false"
            return f"{{ path = {json.dumps(path.as_posix())}, editable = {editable} }}"
    # uv's editable installs of a workspace write no direct_url.json
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file():
        return f"{{ path = {json.dumps(checkout.as_posix())}, editable = true }}"
    return '{ git = "https://github.com/CANOE-main/CANOE" }'


def cache_dir_entry(cache_dir: Path | None) -> str:
    """
    `cache_dir` of the generated `config/<scenario>/full-pipeline.toml`: `.cache` in
    the project (relative to the TOML's folder) when no cache is given, else the
    absolute path (with `/`, which Windows paths accept too).

    >>> cache_dir_entry(None)
    '../../.cache'
    >>> cache_dir_entry(Path("/data/canoe-cache"))
    '/data/canoe-cache'
    """
    if cache_dir is None:
        return "../../.cache"
    return cache_dir.expanduser().resolve().as_posix()


def create_project(
    project_dir: Path,
    cache_dir: Path | None,
    defaults: bool = False,
    answers: dict[str, Any] | None = None,
) -> Path:
    """
    Render the template into `project_dir`, asking the template's questions (or
    taking their defaults, or the given `answers`). Returns the pipeline TOML of the
    chosen scenario.

    The name question is pre-filled with the folder name (see the template's
    `copier.yml`), so with `defaults` the folder name is the project name.
    """
    data = {
        **(answers or {}),
        "canoe_source": canoe_source(),
        "cache_dir": cache_dir_entry(cache_dir),
    }
    worker = run_copy(
        str(template_dir()),
        project_dir,
        data=data,
        defaults=defaults,
        # Copier's file list and "template version None" (an installed template
        # has no git version); `canoe init` says what it created
        quiet=True,
    )
    scenario = worker.answers.combined["scenario"]
    return project_dir / "config" / str(scenario) / "full-pipeline.toml"

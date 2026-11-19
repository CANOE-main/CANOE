"""
Paths written in configuration files, relative to the file they are written in.

A TOML loaded from a file (`canoe.pipeline.load_pipeline_config`) is validated with
the file's folder as `config_dir` in the validation context, and `ConfigPath` fields
join a relative value onto it. So `db_output_dir = "../canoe-pwd/canoe.sqlite"` names
the same database whichever folder the pipeline is run from, and a project can keep
one folder of TOMLs per scenario.

Relative paths stay relative to the working directory when there is no `config_dir`
(configs built in memory, e.g. in tests) and for field defaults, which pydantic does
not validate: a default like `working_directory = ./canoe-pwd` is where the pipeline
runs, not where its TOML is.
"""

import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, ValidationInfo


def join_config_dir(value: Path, config_dir: Path | None) -> Path:
    """
    `value` (with `~` expanded) under `config_dir`, if it is relative and there is
    a `config_dir`. The `..` of the joined path are collapsed (`os.path.normpath`) so
    logs show `canoe-pwd/canoe.sqlite`, not `configuration/../canoe-pwd/canoe.sqlite`.

    >>> join_config_dir(Path("sectors/commercial.toml"), Path("config/all-high"))
    PosixPath('config/all-high/sectors/commercial.toml')
    >>> join_config_dir(Path("../../canoe-pwd/canoe.sqlite"), Path("config/all-high"))
    PosixPath('canoe-pwd/canoe.sqlite')
    >>> join_config_dir(Path("/data/canoe.sqlite"), Path("config"))
    PosixPath('/data/canoe.sqlite')
    >>> join_config_dir(Path("canoe.sqlite"), None)
    PosixPath('canoe.sqlite')
    """
    value = value.expanduser()
    if config_dir is None or value.is_absolute():
        return value
    return Path(os.path.normpath(config_dir / value))


def config_dir_of(info: ValidationInfo) -> Path | None:
    """Folder of the configuration file being validated, if it came from a file."""
    context: dict[str, Any] = info.context or {}
    config_dir = context.get("config_dir")
    return None if config_dir is None else Path(config_dir)


def _resolve_config_path(value: Path, info: ValidationInfo) -> Path:
    """`value` relative to the folder of the configuration file it was read from."""
    return join_config_dir(value, config_dir_of(info))


ConfigPath = Annotated[Path, AfterValidator(_resolve_config_path)]
"""A path in a configuration file: relative to that file's folder (see the module
docstring)."""

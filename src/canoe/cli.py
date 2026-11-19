"""
The `canoe` command.

    canoe run config/all-high/full-pipeline.toml      # compiler, rep. periods, Temoa
    canoe compile config/all-high/full-pipeline.toml  # compiler only
    canoe check config/all-high/full-pipeline.toml    # validate the TOMLs, run nothing
    canoe cache install [FOLDER]                      # download the data cache
    canoe cache status [FOLDER] [--date YYYY-MM-DD]   # what a cache folder holds

The configuration is a positional argument: a project keeps one folder per scenario
(`config/<scenario>/full-pipeline.toml`), and the scenario is what changes between
runs. Relative paths in the TOMLs are relative to each TOML's folder (see
`canoe.common.config_paths`), so the commands work from any folder.

The data cache has no machine-wide location: the user says where it is (or installs
it in the project, `.cache`), and the pipeline TOML names it in `cache_dir`. `run`
and `compile` stop before starting if it lacks the snapshot the TOML reads.
"""

import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from pydantic import ValidationError

from .common.cache_connector.install import (
    CacheContents,
    cache_contents,
    install_cache,
)
from .pipeline import CANOEPipelineConfig, load_pipeline_config, run, run_compiler

app = typer.Typer(
    help="The Canadian Open Energy Model (CANOE).",
    no_args_is_help=True,
    add_completion=False,
    # The locals of a failed run hold whole configs and data frames
    pretty_exceptions_show_locals=False,
)


def _print_version(value: bool) -> None:
    """Eager `--version` callback: print the version and exit."""
    if value:
        typer.echo(f"canoe {version('canoe')}")
        raise typer.Exit


@app.callback()
def _main(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the version of canoe and exit.",
        ),
    ] = False,
) -> None:
    """The Canadian Open Energy Model (CANOE)."""


def _load_config(config: Path) -> CANOEPipelineConfig:
    """
    The pipeline configuration at `config`, or exit with the reason it can't be
    read: a missing TOML (the pipeline's or one it names), a TOML syntax error or a
    setting the models reject. These are mistakes in the user's files, so they get
    a message instead of a traceback.
    """
    try:
        return load_pipeline_config(config)
    except FileNotFoundError as error:
        typer.secho(f"File not found: {error.filename}", fg="red", err=True)
    except tomllib.TOMLDecodeError as error:
        typer.secho(f"Invalid TOML in {config}: {error}", fg="red", err=True)
    except ValidationError as error:
        typer.secho(f"Invalid configuration in {config}:", fg="red", err=True)
        typer.echo(str(error), err=True)
    raise typer.Exit(code=1)


def _missing_cache(config: CANOEPipelineConfig) -> str | None:
    """
    What the compiler of `config` would miss in its data cache, with how to install
    it; None if it has no compiler or the cache has the snapshot it reads.
    """
    if config.compiler is None:
        return None
    cache = config.compiler.base.data_cache_config
    contents = cache_contents(cache.cache_dir)
    if contents.has(cache.cache_date):
        return None
    missing: list[str] = []
    if cache.cache_date not in contents.snapshots:
        missing.append(f"the {cache.cache_date} snapshot")
    if not contents.renewables:
        missing.append("the renewables")
    return (
        f"The data cache at {cache.cache_dir} lacks {' and '.join(missing)}. "
        + f"Install it with: canoe cache install {cache.cache_dir}"
    )


def _load_runnable_config(config: Path) -> CANOEPipelineConfig:
    """`_load_config`, also exiting if the compiler would not find its data cache."""
    pipeline_config = _load_config(config)
    missing = _missing_cache(pipeline_config)
    if missing is not None:
        typer.secho(missing, fg="red", err=True)
        raise typer.Exit(code=1)
    return pipeline_config


ConfigArgument = Annotated[
    Path,
    typer.Argument(
        exists=True,
        dir_okay=False,
        metavar="CONFIG",
        help="Pipeline TOML, e.g. config/all-high/full-pipeline.toml.",
    ),
]


@app.command(name="run")
def run_command(config: ConfigArgument) -> None:
    """Run the pipeline: compiler, representative periods and Temoa, as configured."""
    run(_load_runnable_config(config))


@app.command(name="compile")
def compile_command(config: ConfigArgument) -> None:
    """Run the compiler only: build the database, without rep. periods or Temoa."""
    pipeline_config = _load_runnable_config(config)
    if pipeline_config.compiler is None:
        typer.secho(
            f"{config} has no [compiler] (it reads input_database): nothing to compile",
            fg="red",
            err=True,
        )
        raise typer.Exit(code=1)
    if pipeline_config.representative_periods_config is not None:
        logger.info("Compiling only: ignoring [representative_periods_config]")
    if pipeline_config.temoa_config is not None:
        logger.info("Compiling only: ignoring [temoa_config]")
    run_compiler(pipeline_config.compiler)


@app.command()
def check(
    config: ConfigArgument,
    show: Annotated[
        bool,
        typer.Option(
            "--show",
            help="Print the resolved configuration (inherited settings and paths "
            + "filled in) as JSON.",
        ),
    ] = False,
) -> None:
    """
    Validate a configuration and the TOMLs it names, and check its data cache,
    without running anything.
    """
    pipeline_config = _load_config(config)
    if show:
        typer.echo(pipeline_config.model_dump_json(indent=2))
        return
    typer.secho(f"{config}: valid", fg="green")
    # A warning only: the config itself is fine, and the cache can come later
    missing = _missing_cache(pipeline_config)
    if missing is not None:
        typer.secho(missing, fg="yellow")


cache_app = typer.Typer(
    help="The local copy of the CANOE data lake that the compiler reads.",
    no_args_is_help=True,
)
app.add_typer(cache_app, name="cache")


def _describe(cache_dir: Path, contents: CacheContents) -> str:
    """One line on what `cache_dir` holds."""
    if contents.is_empty():
        return f"{cache_dir}: no cache"
    snapshots = ", ".join(contents.snapshots) or "none"
    renewables = "yes" if contents.renewables else "missing"
    return f"{cache_dir}: snapshots {snapshots}; renewables {renewables}"


@cache_app.command()
def install(
    cache_dir: Annotated[
        Path | None,
        typer.Argument(
            metavar="[FOLDER]",
            help="Folder of the cache; asked for if left out (.cache in the current "
            + "folder by default).",
            file_okay=False,
        ),
    ] = None,
) -> None:
    """
    Download the data cache (a few GB) and add its new files to a folder.

    Files already in the folder are never overwritten: a newer download only adds
    its new snapshot.
    """
    if cache_dir is None:
        cache_dir = Path(
            typer.prompt("Folder of the CANOE data cache", default=".cache")
        )
    cache_dir = cache_dir.expanduser()
    typer.echo(f"Before: {_describe(cache_dir, cache_contents(cache_dir))}")
    contents = install_cache(cache_dir)
    typer.secho(f"Installed: {_describe(cache_dir, contents)}", fg="green")
    typer.echo(
        "Pipelines read it from cache_dir in [compiler.base.data_cache_config], "
        + "relative to the folder of the pipeline TOML."
    )


@cache_app.command()
def status(
    cache_dir: Annotated[
        Path,
        typer.Argument(
            metavar="[FOLDER]", help="Folder of the cache.", file_okay=False
        ),
    ] = Path(".cache"),
    cache_date: Annotated[
        str | None,
        typer.Option("--date", help="Snapshot (YYYY-MM-DD) a pipeline needs."),
    ] = None,
) -> None:
    """Show the snapshots a cache folder holds; exit 1 if --date is not usable."""
    contents = cache_contents(cache_dir)
    typer.echo(_describe(cache_dir, contents))
    if cache_date is not None and not contents.has(cache_date):
        typer.secho(
            f"Not usable for {cache_date}: install it with "
            + f"canoe cache install {cache_dir}",
            fg="red",
            err=True,
        )
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

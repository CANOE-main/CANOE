"""
The `canoe` command.

    canoe run config/all-high/full-pipeline.toml      # compiler, rep. periods, Temoa
    canoe compile config/all-high/full-pipeline.toml  # compiler only
    canoe check config/all-high/full-pipeline.toml    # validate the TOMLs, run nothing

The configuration is a positional argument: a project keeps one folder per scenario
(`config/<scenario>/full-pipeline.toml`), and the scenario is what changes between
runs. Relative paths in the TOMLs are relative to each TOML's folder (see
`canoe.common.config_paths`), so the commands work from any folder.
"""

import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from pydantic import ValidationError

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
    run(_load_config(config))


@app.command(name="compile")
def compile_command(config: ConfigArgument) -> None:
    """Run the compiler only: build the database, without rep. periods or Temoa."""
    pipeline_config = _load_config(config)
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
    """Validate a configuration and the TOMLs it names, without running anything."""
    pipeline_config = _load_config(config)
    if show:
        typer.echo(pipeline_config.model_dump_json(indent=2))
    else:
        typer.secho(f"{config}: valid", fg="green")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

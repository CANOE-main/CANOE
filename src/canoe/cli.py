import tomllib
from pathlib import Path
from typing import Annotated

import typer

from .pipeline import CANOEPipelineConfig, run

app = typer.Typer()


@app.command()
def run_pipeline(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to the configuration file")
    ],
) -> None:
    """Run the CANOE pipeline with the given configuration file."""
    with config.open("rb") as f:
        pipeline_config = CANOEPipelineConfig.model_validate(tomllib.load(f))
    run(pipeline_config)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

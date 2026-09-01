from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from canoe.representative_periods.config import RepresentativePeriodsConfig
from canoe.representative_periods.process_all import run_representative_periods

from .initializer import CANOEBaseConfig
from .initializer import run as run_initializer
from .sector_config import SectorConfig, resolve_sector_config
from .temoa_protocol import CANOETemoaConfig, run_temoa


class CANOECompilerConfig(BaseModel):
    base: CANOEBaseConfig
    sectors: dict[str, SectorConfig] = Field(default_factory=dict)

    @field_validator("sectors", mode="before")
    @classmethod
    def _resolve_sectors(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, dict):
            return value
        base = (info.data or {}).get("base")
        return {key: resolve_sector_config(item, base) for key, item in value.items()}


class CANOEPipelineConfig(BaseModel):
    working_directory: Path = Path("./canoe-pwd")
    compiler: CANOECompilerConfig | None = None
    input_database: Path | None = None
    representative_periods_config: RepresentativePeriodsConfig | None = None
    temoa_config: CANOETemoaConfig | None = None

    @model_validator(mode="after")
    def check_exclusive_fields(self) -> "CANOEPipelineConfig":
        fields_set = sum(
            1 for field in (self.compiler, self.input_database) if field is not None
        )

        if fields_set != 1:
            raise ValueError(
                "You must provide exactly one of 'compiler' or 'input_database'."
            )

        return self

    @property
    def db_path(self) -> Path:
        if self.input_database is not None:
            return self.input_database
        if self.compiler is not None:
            return self.compiler.base.db_output_dir
        raise RuntimeError("No database path source is set.")


def run(config: CANOEPipelineConfig):
    # Potentially changing throughout the pipeline
    db_path = config.db_path

    # Compiler
    if config.compiler is not None:
        if config.compiler.base.data_cache_config.force_sync:
            # TODO
            ...

        run_initializer(config.compiler.base)

        for sector_name, sector_config in config.compiler.sectors.items():
            logger.info(f"Running sector: {sector_name}")
            sector_output = sector_config.run()
            logger.info(f"Sector {sector_name} output: {sector_output}")

        # Fuel imports
        # sector_output.fuel_imports

    # Representative periods
    if config.representative_periods_config is not None:
        logger.info("Processing representative periods...")
        db_path = run_representative_periods(
            db_path, config.working_directory, config.representative_periods_config
        )

    # Run TEMOA
    if config.temoa_config is not None:
        logger.info("Running TEMOA...")
        run_temoa(db_path, config.temoa_config)

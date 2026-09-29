from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from canoe.common import CANOEModuleOutput, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier
from canoe.emissions import processing as emissions_processing
from canoe.fuel.config import CANOEFuelConfig
from canoe.representative_periods.config import RepresentativePeriodsConfig
from canoe.representative_periods.process_all import run_representative_periods

from .initializer import CANOEBaseConfig
from .initializer import run as run_initializer
from .sector_config import SectorConfig, resolve_sector_config
from .temoa_protocol import CANOETemoaConfig, run_temoa


class CANOECompilerConfig(BaseModel):
    base: CANOEBaseConfig
    sectors: dict[str, SectorConfig] = Field(default_factory=dict)
    fuel: CANOEFuelConfig | None = None
    """Supplies the fuels the sectors import; none supplied if left out."""

    @field_validator("sectors", mode="before")
    @classmethod
    def _resolve_sectors(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, dict):
            return value
        base = (info.data or {}).get("base")
        return {key: resolve_sector_config(item, base) for key, item in value.items()}

    @field_validator("fuel", mode="before")
    @classmethod
    def _resolve_fuel(cls, value: Any, info: ValidationInfo) -> Any:
        # Inline table: validated with `base` in context so inherited fields resolve
        if not isinstance(value, dict):
            return value
        base = (info.data or {}).get("base")
        return CANOEFuelConfig.model_validate(value, context={"base": base})


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
            raise NotImplementedError(
                "Forcing canoe-lake sync has not been implemented yet."
            )

        base = config.compiler.base

        # Initialize empty database
        run_initializer(base)

        with atomic_transaction(base.db_output_dir) as db_conn:
            # Emission commodities, before the sectors write emission activities.
            # The last future period is the end of the horizon, not a model period.
            emissions_processing.init(
                db_conn,
                base.emissions,
                base.provinces,
                base.future_periods[:-1],
                DatasetIdentifier(
                    sector=CANOESector.Electricity,
                    code_description="HR",
                    version=base.data_version,
                ),
            )

        # Run each sector
        module_outputs: list[CANOEModuleOutput] = []
        for sector_name, sector_config in config.compiler.sectors.items():
            logger.info(f"Running sector: {sector_name}")
            sector_output = sector_config.run()
            logger.info(f"Sector {sector_name} output: {sector_output}")
            module_outputs.append(sector_output)

        # Fuel supply: imports and distribution of the fuels the sectors consume
        fuel_imports = [i for output in module_outputs for i in output.fuel_imports]
        if config.compiler.fuel is not None:
            logger.info("Running fuel supply")
            module_outputs.append(config.compiler.fuel.run(fuel_imports))
        elif fuel_imports:
            logger.warning(
                f"No [compiler.fuel] configured: {len(fuel_imports)} fuel imports of "
                + "the sectors are not supplied"
            )

        logger.info("Processing emissions...")
        with atomic_transaction(base.db_output_dir) as db_conn:
            # Emissions: check declarations and derive CO2-equivalents
            emissions_processing.finalize(
                db_conn,
                base.emissions,
                [d for output in module_outputs for d in output.emissions],
            )

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

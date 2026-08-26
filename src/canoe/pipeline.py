from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .initializer import CANOEBaseConfig
from .initializer import run as run_initializer
from .sector_config import SectorConfig, resolve_sector_config


class CANOEPipelineConfig(BaseModel):
    base: CANOEBaseConfig
    sectors: dict[str, SectorConfig] = Field(default_factory=dict)

    @field_validator("sectors", mode="before")
    @classmethod
    def _resolve_sectors(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, dict):
            return value
        base = (info.data or {}).get("base")
        return {key: resolve_sector_config(item, base) for key, item in value.items()}


def run(config: CANOEPipelineConfig):
    if config.base.data_cache_config.force_sync:
        # TODO
        ...

    run_initializer(config.base)

    for sector_name, sector_config in config.sectors.items():
        logger.info(f"Running sector: {sector_name}")
        sector_output = sector_config.run()
        logger.info(f"Sector {sector_name} output: {sector_output}")

    # Fuel imports
    # sector_output.fuel_imports

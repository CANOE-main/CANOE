"""
Resolves sector configuration TOML paths into typed config objects.

Each entry under `sectors` in the pipeline TOML is a path (string) to that
sector's own TOML file. This module reads that file, then validates it
against the `module_name`-discriminated `SectorConfig` union with the
pipeline's `base` config available in context so `Inherited` fields
(see `.inheritance`) can resolve.
"""

import tomllib
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, TypeAdapter

from .commercial.config import CANOECommercialConfig
from .initializer import CANOEBaseConfig

# Add new sector configs here as they're implemented, e.g.:
# SectorConfig = Annotated[CANOECommercialConfig | CANOEResidentialConfig, Field(discriminator="module_name")]
SectorConfig = Annotated[CANOECommercialConfig, Field(discriminator="module_name")]

_SECTOR_CONFIG_ADAPTER: TypeAdapter[Any] = TypeAdapter(SectorConfig)


def resolve_sector_config(value: Any, base: CANOEBaseConfig | None) -> Any:
    """Turn a path/dict into a fully-validated sector config instance.

    - A string/Path is read as TOML.
    - A dict is validated as given (lets configs be built in-memory, e.g. in tests).
    - Anything else (already a model instance) passes through untouched.

    Dispatch to the right sector model is handled by the `module_name`-discriminated
    `SectorConfig` union, so adding a sector only requires adding it there.
    """
    if isinstance(value, (str, Path)):
        with Path(value).open("rb") as f:
            raw = tomllib.load(f)
    elif isinstance(value, dict):
        raw = value  # pyright: ignore[reportUnknownVariableType]
    else:
        return value

    return _SECTOR_CONFIG_ADAPTER.validate_python(raw, context={"base": base})

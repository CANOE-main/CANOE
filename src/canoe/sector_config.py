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

from .agriculture.config import CANOEAgricultureConfig
from .commercial.config import CANOECommercialConfig
from .common.config_paths import join_config_dir
from .ghost.config import CANOEGhostConfig
from .industry.config import CANOEIndustryConfig
from .initializer import CANOEBaseConfig
from .residential.config import CANOEResidentialConfig

# Add new sector configs here as they're implemented
SectorConfig = Annotated[
    CANOECommercialConfig
    | CANOEAgricultureConfig
    | CANOEIndustryConfig
    | CANOEResidentialConfig
    | CANOEGhostConfig,
    Field(discriminator="module_name"),
]

_SECTOR_CONFIG_ADAPTER: TypeAdapter[Any] = TypeAdapter(SectorConfig)


def resolve_sector_config(
    value: Any, base: CANOEBaseConfig | None, config_dir: Path | None = None
) -> Any:
    """Turn a path/dict into a fully-validated sector config instance.

    - A string/Path is read as TOML: relative to `config_dir` (the folder of the
      pipeline TOML naming it) if given, and the paths inside it relative to its
      own folder (see `canoe.common.config_paths`).
    - A dict is validated as given (lets configs be built in-memory, e.g. in tests),
      its paths relative to `config_dir`.
    - Anything else (already a model instance) passes through untouched.

    Dispatch to the right sector model is handled by the `module_name`-discriminated
    `SectorConfig` union, so adding a sector only requires adding it there.
    """
    if isinstance(value, (str, Path)):
        path = join_config_dir(Path(value), config_dir)
        with path.open("rb") as f:
            raw = tomllib.load(f)
        config_dir = path.parent
    elif isinstance(value, dict):
        raw = value
    else:
        return value

    return _SECTOR_CONFIG_ADAPTER.validate_python(
        raw, context={"base": base, "config_dir": config_dir}
    )

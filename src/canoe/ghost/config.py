"""
Configuration of a ghost sector, an inline table of `[compiler.sectors]` in the
pipeline TOML (e.g. `[compiler.sectors.transportation]`).

A ghost stands in for the end-use tree of a sector that is added to the database
after the pipeline runs. It builds no technologies: it registers the sector's fuel
commodities (e.g. `T_elc`) and declares them as fuel imports, so the electricity and
fuel modules supply them. Until the tree is added nothing consumes them, and Temoa's
source trace drops the supply technologies as demand orphans.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, override

from pydantic import ConfigDict, field_validator

from canoe.common import (
    CANOEFuel,
    CANOEModule,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    naming,
)
from canoe.common.validation import ValidationBehavior
from canoe.ghost.build import build_ghost

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class CANOEGhostConfig(InheritsFromBase, CANOEModule):
    """
    Ghost sector, `module_name = "ghost"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the ghost's table.

    Examples
    --------
    >>> config = CANOEGhostConfig.model_validate(
    ...     {
    ...         "module_name": "ghost",
    ...         "data_version": "001",
    ...         "database_file": "canoe.sqlite",
    ...         "provinces": ["ON", "QC"],
    ...         "sector": "TRP",
    ...         "fuels": ["ELC", "GSL"],
    ...     }
    ... )
    >>> print(config.get_sector(), config.get_dataset_code())
    Transportation TRPHR001
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["ghost"]
    """Selects this module in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. TRPHR003). Inherited."""

    dataset_code_description: str = "HR"
    """Code between the sector and the version in the data set codes (e.g. HR in
    TRPHR003), to tell the rows of a ghost apart from those of the tree added later."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    # Model scope
    provinces: list[CANOEProvince] = inherit()
    """Provinces where the tree will take the fuels. Inherited; set it to reserve
    them in some provinces only."""

    sector: CANOESector
    """End-use sector the tree belongs to, by name or code (e.g. `TRP`)."""

    fuels: list[CANOEFuel]
    """Fuels the tree will take as input."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the provinces of this ghost."""

    @field_validator("dataset_code_description")
    @classmethod
    def _check_dataset_code_description(cls, value: str) -> str:
        if not (value.isalpha() and value.isupper()):
            raise ValueError(f"must be uppercase letters, got '{value}'")
        return value

    @field_validator("sector")
    @classmethod
    def _check_end_use(cls, value: CANOESector) -> CANOESector:
        if value in (CANOESector.Electricity, CANOESector.Fuel):
            raise ValueError(f"{value} is a supply module, not an end-use sector")
        return value

    @field_validator("fuels")
    @classmethod
    def _check_fuels(cls, value: list[CANOEFuel]) -> list[CANOEFuel]:
        if not value:
            raise ValueError("at least one fuel is needed")
        duplicates = {f for f in value if value.count(f) > 1}
        if duplicates:
            raise ValueError(f"fuels listed more than once: {duplicates}")
        return value

    @override
    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=self.sector,
            resolution_str=self.dataset_code_description,
            version_code=self.data_version,
            province=None,
        )

    @override
    def get_sector(self) -> CANOESector:
        return self.sector

    @override
    def run(self) -> CANOEModuleOutput:
        return build_ghost(self)

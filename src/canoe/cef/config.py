"""
Configuration of a CEF sector, a low-resolution version of an end-use sector built
from the CER Canada's Energy Future 2023 end-use demand projections (see
`configuration/cef-default.toml`).

Any sector CEF reports (commercial, residential, industry, transportation) can be a
CEF sector: its TOML (or inline table of `[compiler.sectors]`) sets
`module_name = "cef"` and the `sector`. The sector is a single technology (e.g.
`T_TRP`) with unlimited capacity that turns the sector fuels into the sector energy
demand (e.g. `T_D_TRP`) with efficiency 1; the demand is the CEF energy demand of the
sector, and annual input splits fix the CEF fuel mix of each period.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, override

from canoe_schema.v4_0 import OperatorCode
from pydantic import ConfigDict, field_validator

from canoe.cef.build import build_cef
from canoe.cef.energy_mix import SmallShareStrategy
from canoe.common import (
    CANOEModule,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.projections import (
    CERScenario,
    DemandProjectionPoint,
    RejectsDeprecatedProjectionFields,
)
from canoe.common.validation import ValidationBehavior

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class CANOECEFConfig(RejectsDeprecatedProjectionFields, InheritsFromBase, CANOEModule):
    """
    CEF sector, `module_name = "cef"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the sector TOML.

    Examples
    --------
    >>> config = CANOECEFConfig.model_validate(
    ...     {
    ...         "module_name": "cef",
    ...         "data_version": "003",
    ...         "database_file": "canoe.sqlite",
    ...         "data_cache_config": {"cache_date": "2026-08-10"},
    ...         "future_periods": [2025, 2030],
    ...         "period_step": 5,
    ...         "provinces": ["ON", "QC"],
    ...         "demand_projection_point": "period_end",
    ...         "sector": "TRP",
    ...         "scenario": "Current Measures",
    ...     }
    ... )
    >>> print(config.get_sector(), config.get_dataset_code())
    Transportation TRPCM003
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["cef"]
    """Selects this module in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. TRPCM003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Model periods, the ones written. Inherited."""

    period_step: int = inherit()
    """Length of the last period, in years; with `period_end`, the CEF year read by
    the last period is its end. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    sector: CANOESector
    """End-use sector built from CEF, by name or code (e.g. `TRP`): commercial,
    residential, industry or transportation. CEF industry includes agriculture."""

    # Data
    scenario: CERScenario
    """CER Canada's Energy Future scenario whose demand is read. Its code goes in the
    data set codes (e.g. CM in TRPCM003)."""

    demand_projection_point: DemandProjectionPoint = inherit()
    """Year of each period whose CEF demand it takes: `period_end` (e.g. 2030 for
    period 2025) or `period_start` (2025). Inherited; `legacy` does not apply, as
    CEF demands are not projected from a base year."""

    # Fuel mix
    small_share_threshold: float = 0.02
    """Fuel shares of the sector energy demand below this become zero."""

    small_share_strategy: SmallShareStrategy = SmallShareStrategy.ZeroSmallShares
    """What happens to the energy of the fuels below `small_share_threshold`."""

    input_split_operator: OperatorCode = OperatorCode.LE
    """Operator of the input splits: upper bound (`le`), exact share (`e`) or lower
    bound (`ge`). The splits of a province and period add up to 1, so `le` fixes the
    shares as `e` does; with `ge`, fuels with a zero share are not kept out."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods or regions this sector needs."""

    @field_validator("sector")
    @classmethod
    def _check_sector(cls, value: CANOESector) -> CANOESector:
        if value.get_cef_sector() is None:
            raise ValueError(
                f"CEF has no {value} sector; options: "
                + ", ".join(s.value for s in CANOESector if s.get_cef_sector())
            )
        return value

    @field_validator("demand_projection_point")
    @classmethod
    def _check_demand_projection_point(
        cls, value: DemandProjectionPoint
    ) -> DemandProjectionPoint:
        if value == DemandProjectionPoint.Legacy:
            raise ValueError(
                "'legacy' does not apply to CEF demands, which are not projected "
                + "from a base year; set 'period_end' or 'period_start' in the CEF "
                + "sector"
            )
        return value

    @field_validator("small_share_threshold")
    @classmethod
    def _check_small_share_threshold(cls, value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError(f"must be in [0, 1), got {value}")
        return value

    @override
    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=self.sector,
            resolution_str=self.scenario.get_dataset_code_description(),
            version_code=self.data_version,
            province=None,
        )

    @override
    def get_sector(self) -> CANOESector:
        return self.sector

    @override
    def run(self) -> CANOEModuleOutput:
        return build_cef(self)

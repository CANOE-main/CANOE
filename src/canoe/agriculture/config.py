"""
Configuration of the CANOE agriculture sector, one TOML file per run (see
`configuration/agriculture-default.toml`).

The sector is a single technology (`A_AGRI`) with unlimited capacity that turns the
agriculture fuels into the agriculture energy demand with efficiency 1. The demand is
the NRCan CEUD total agriculture energy use, projected with GDP, and the fuel mix is
fixed by annual input splits computed with the selected `InputSplitStrategy`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, override

from canoe_schema.v4_0 import OperatorCode
from pydantic import ConfigDict, field_validator, model_validator

from canoe.agriculture.build import build_agriculture
from canoe.agriculture.input_splits import InputSplitStrategy
from canoe.agriculture.loaders import CEUD_AGRICULTURE_SOURCES
from canoe.common import (
    CANOEFuel,
    CANOEModule,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.gdp import CERScenario, GDPProjectionPoint
from canoe.common.validation import ValidationBehavior

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig

SUPPORTED_FUELS: tuple[CANOEFuel, ...] = tuple(
    fuel for fuel in CEUD_AGRICULTURE_SOURCES.values() if fuel is not None
)
"""Fuels with their own row in the NRCan CEUD agriculture tables: ELC, NG, GSL, DSL,
HFO and PROP."""


class CANOEAgricultureConfig(InheritsFromBase, CANOEModule):
    """
    Agriculture sector, `module_name = "agriculture"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the sector TOML.

    Examples
    --------
    >>> config = CANOEAgricultureConfig.model_validate(
    ...     {
    ...         "module_name": "agriculture",
    ...         "data_version": "001",
    ...         "database_file": "canoe.sqlite",
    ...         "data_cache_config": {"cache_date": "2026-08-10"},
    ...         "future_periods": [2025, 2030, 2035],
    ...         "provinces": ["ON", "PEI"],
    ...         "gdp_scenario": "Global Net-zero",
    ...         "gdp_projection_point": "period_end",
    ...         "ceud_data_year": 2022,
    ...         "fuels": ["ELC", "NG", "DSL", "GSL"],
    ...     }
    ... )
    >>> config.remainder_fuel, config.input_split_strategy.value
    (Diesel, 'nrcan_percent_with_remainder')
    >>> config.model_periods
    [2025, 2030]
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["agriculture"]
    """Selects this sector in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. AGRHR003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Temoa's `time_future`, see `model_periods`. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    # Demand projections
    gdp_scenario: CERScenario = inherit()
    """CER scenario of the GDP projections that scale the demand. Inherited."""

    gdp_projection_point: GDPProjectionPoint = inherit()
    """Year of each period at which GDP scales the demand. Inherited."""

    ceud_data_year: int
    """Year of the NRCan CEUD agriculture data read (energy use and fuel mix). GDP
    projections are indexed to this year. Must be a year of the cached tables."""

    # Fuels
    fuels: list[CANOEFuel]
    """Fuels the agriculture technology consumes, among `SUPPORTED_FUELS`. A fuel with
    zero energy use in a region is left out there; missing data is handled by
    `missing_data_behavior`."""

    input_split_strategy: InputSplitStrategy = (
        InputSplitStrategy.NRCanPercentWithRemainder
    )
    """How the CEUD fuel mix becomes the input splits."""

    remainder_fuel: CANOEFuel = CANOEFuel.Diesel
    """Fuel that takes the share of the fuels not modelled. Must be one of `fuels`.
    Only for strategies that use it (see `InputSplitStrategy`)."""

    input_split_operator: OperatorCode = OperatorCode.GE
    """Operator of the input splits: lower bound (`ge`), upper bound (`le`) or exact
    share (`e`)."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods or regions this sector needs."""

    missing_data_behavior: ValidationBehavior = "warning"
    """What to do when the data of a requested fuel is missing in a region."""

    @field_validator("fuels")
    @classmethod
    def _check_fuels(cls, value: list[CANOEFuel]) -> list[CANOEFuel]:
        if not value:
            raise ValueError("at least one fuel is needed")
        duplicates = {f for f in value if value.count(f) > 1}
        if duplicates:
            raise ValueError(f"fuels listed more than once: {duplicates}")
        unsupported = [f for f in value if f not in SUPPORTED_FUELS]
        if unsupported:
            raise ValueError(
                f"fuels {[f.value for f in unsupported]} are not in the NRCan CEUD "
                + f"agriculture tables. Options: {[f.value for f in SUPPORTED_FUELS]}"
            )
        return value

    @model_validator(mode="after")
    def _check_remainder_fuel(self) -> Self:
        if not self.input_split_strategy.uses_remainder_fuel():
            if "remainder_fuel" in self.model_fields_set:
                raise ValueError(
                    "remainder_fuel does not apply to input_split_strategy = "
                    + f"'{self.input_split_strategy.value}'"
                )
            return self
        if self.remainder_fuel not in self.fuels:
            raise ValueError(
                f"remainder_fuel {self.remainder_fuel.value} must be one of fuels "
                + f"{[f.value for f in self.fuels]}"
            )
        return self

    @property
    def model_periods(self) -> list[int]:
        """
        Periods we write parameters for.

        `future_periods` is Temoa's time_future: its last year marks the end of the
        horizon and is not a period itself, e.g. [2025, ..., 2045, 2050] has model
        periods 2025-2045, the last one ending in 2050.
        """
        return self.future_periods[:-1]

    @override
    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=CANOESector.Agriculture,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    @override
    def run(self) -> CANOEModuleOutput:
        return build_agriculture(self)

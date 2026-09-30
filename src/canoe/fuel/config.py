"""
Configuration of the CANOE fuel supply, the `[compiler.fuel]` table of the pipeline
TOML (see `configuration/full-pipeline.toml`).

The fuel module supplies the fuels the sectors consume. It runs after the sectors,
from the fuel imports they declare: for each fuel an import technology (`F_IMP_<FUEL>`,
from the `F_ethos` source to `F_<fuel>`) and, for each sector that consumes it, a
distribution technology (`F_<S>_<FUEL>`, from `F_<fuel>` to the sector's `<S>_<fuel>`).
Their variable costs are the fuel prices (see `canoe.fuel.prices`) and their emission
activities the upstream and combustion emissions of the fuels.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Self

from pydantic import ConfigDict, model_validator

from canoe.common import (
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.periods import ProjectionPoint
from canoe.common.validation import ValidationBehavior
from canoe.fuel.build import build_fuel
from canoe.fuel.prices import PREVIOUS_MODULE_CURRENCY_YEAR

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class CANOEFuelConfig(InheritsFromBase):
    """
    Fuel supply, `[compiler.fuel]` in the pipeline TOML.

    Not an end-use sector: it runs once all sectors have run, with their fuel imports (see
    `run`). Fields marked as inherited take their value from `[compiler.base]` unless
    set in `[compiler.fuel]`.

    Examples
    --------
    >>> config = CANOEFuelConfig.model_validate(
    ...     {
    ...         "data_version": "001",
    ...         "database_file": "canoe.sqlite",
    ...         "data_cache_config": {"cache_date": "2026-08-10"},
    ...         "future_periods": [2025, 2030],
    ...         "period_step": 5,
    ...         "provinces": ["ON", "PEI"],
    ...         "price_projection_point": "period_end",
    ...         "model_currency_year": 2020,
    ...     }
    ... )
    >>> config.reproduce_previous_price_errors
    False
    >>> config.get_dataset_code()
    'FUELHR001'
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. FUELHR003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Model periods, the ones written. Inherited."""

    period_step: int = inherit()
    """Length of the last period, in years; prices read at the period end take the
    end of the horizon for it. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    # Prices
    price_projection_point: ProjectionPoint = inherit()
    """Year of each period at which the projected fuel prices are read. Inherited."""

    model_currency_year: int = inherit()
    """Year of the Canadian dollars the fuel prices are written in. Inherited."""

    reproduce_previous_price_errors: bool = False
    """Reproduce the price errors of the previous fuel module, to compare with its
    databases: $/MMBtu multiplied by 1.055 instead of divided, fixed exchange rate
    and deflators (the 2025 deflator applied to 2024 dollars), and residential LPG
    priced as transportation propane. See `FUEL_MODULE_BUGS.md`. Temporary."""

    # Emissions
    reproduce_previous_emission_errors: bool = False
    """Reproduce the emission errors of the previous fuel module, to compare with its
    databases: agriculture gasoline without combustion factors (instead of the
    transportation ones, see `canoe.fuel.emission_factors`). See
    `FUEL_MODULE_BUGS.md`. Temporary."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods, regions or commodities this
    module needs."""

    missing_data_behavior: ValidationBehavior = "warning"
    """What to do when a fuel a sector imports has no price or emission factors."""

    @model_validator(mode="after")
    def _check_previous_price_errors(self) -> Self:
        if (
            self.reproduce_previous_price_errors
            and self.model_currency_year != PREVIOUS_MODULE_CURRENCY_YEAR
        ):
            raise ValueError(
                "reproduce_previous_price_errors converts prices to "
                + f"{PREVIOUS_MODULE_CURRENCY_YEAR} CAD, as the previous module; set "
                + f"model_currency_year = {PREVIOUS_MODULE_CURRENCY_YEAR} or turn it off"
            )
        return self

    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=CANOESector.Fuel,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    def run(self, fuel_imports: list[CANOEFuelImport]) -> CANOEModuleOutput:
        """Supply `fuel_imports`, the fuel imports declared by all the sectors."""
        return build_fuel(self, fuel_imports)

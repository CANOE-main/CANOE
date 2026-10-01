"""
Configuration of the CANOE industry sector, one TOML file per run (see
`configuration/industry-default.toml`).

Each industry subsector of the NRCan CEUD is a technology (e.g. `I_PULP`) with
unlimited capacity that turns the industry fuels into the subsector's energy demand
(`I_D_PULP`) with efficiency 1. The demand is the CEUD energy use of the subsector,
projected with GDP, and the fuel mix is fixed by annual input splits from the CEUD
fuel shares.
"""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, override

from canoe_schema.v4_0 import OperatorCode
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from canoe.industry.build import build_industry
from canoe.industry.loaders import CEUD_INDUSTRY_SOURCES
from canoe.industry.subsectors import IndustrySubsector

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig

SUPPORTED_FUELS: tuple[CANOEFuel, ...] = tuple(
    f for f in CEUD_INDUSTRY_SOURCES.values() if f != CANOEFuel.Other
)
"""Fuels with their own row in the NRCan CEUD industry tables, which the fuel module
supplies: ELC, NG, DSL, HFO, PCK, NGL, COAL, COKE and WOOD. "Other" (`OTH`) is not
listed in `fuels`; `other_fuels` decides what happens to it."""


class OtherFuelsTreatment(StrEnum):
    """
    What happens to the NRCan CEUD "Other" energy source (`OTH`) of the industry
    subsectors. It is a mix of non-standard fuels (e.g. waste fuels in cement) with no
    price or emission factors in the fuel module, so it is never a fuel import. See
    `INDUSTRY_MODULE_BUGS.md`, 1.
    """

    Deduct = "deduct"
    """Leave "Other" out: its energy use is deducted from the demand of the
    subsector, and the input splits are the shares of the rest of its energy use. The
    modelled fuels meet only the energy use they met in the CEUD year."""

    Free = "free"
    """Keep "Other" as an input of the subsectors that use it (`I_oth`), with its
    CEUD share as input split, supplied by the industry module at no cost and with no
    emissions. The demand is all the energy use of the subsector. Reproduces the
    previous module (free `F_I_OTH`)."""


def _check_fuel_list(value: list[CANOEFuel]) -> list[CANOEFuel]:
    """Fuels of the sector or of a subsector: at least one, no duplicates, supported"""
    if not value:
        raise ValueError("at least one fuel is needed")
    duplicates = {f for f in value if value.count(f) > 1}
    if duplicates:
        raise ValueError(f"fuels listed more than once: {duplicates}")
    if CANOEFuel.Other in value:
        raise ValueError(
            "OTH is not listed in fuels: other_fuels decides whether it is deducted "
            + "from the demands or supplied for free"
        )
    unsupported = [f for f in value if f not in SUPPORTED_FUELS]
    if unsupported:
        raise ValueError(
            f"fuels {[f.value for f in unsupported]} are not in the NRCan CEUD "
            + f"industry tables. Options: {[f.value for f in SUPPORTED_FUELS]}"
        )
    return value


class IndustrySubsectorConfig(BaseModel):
    """
    One industry subsector, `[subsectors."<subsector>"]` in TOML. Every subsector is
    modelled unless its table sets `skip = true`.

    Examples
    --------
    >>> IndustrySubsectorConfig(fuels=["ELC", "NG"]).fuels
    [Electricity, NaturalGas]
    >>> IndustrySubsectorConfig().skip, IndustrySubsectorConfig().fuels
    (False, None)
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    skip: bool = False
    """Leave the subsector out of the model: no demand and no technology."""

    fuels: list[CANOEFuel] | None = None
    """Fuels the subsector's technology consumes, among `SUPPORTED_FUELS`, instead of
    the sector's `fuels`. Leave out to use the sector's."""

    @field_validator("fuels")
    @classmethod
    def _check_fuels(cls, value: list[CANOEFuel] | None) -> list[CANOEFuel] | None:
        return None if value is None else _check_fuel_list(value)

    @model_validator(mode="after")
    def _check_skipped_without_options(self) -> Self:
        if self.skip and "fuels" in self.model_fields_set:
            raise ValueError("fuels does not apply to a skipped subsector")
        return self


class CANOEIndustryConfig(InheritsFromBase, CANOEModule):
    """
    Industry sector, `module_name = "industry"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the sector TOML.

    Examples
    --------
    >>> config = CANOEIndustryConfig.model_validate(
    ...     {
    ...         "module_name": "industry",
    ...         "data_version": "001",
    ...         "database_file": "canoe.sqlite",
    ...         "data_cache_config": {"cache_date": "2026-08-10"},
    ...         "future_periods": [2025, 2030],
    ...         "period_step": 5,
    ...         "provinces": ["ON", "PEI"],
    ...         "gdp_scenario": "Global Net-zero",
    ...         "gdp_projection_point": "period_end",
    ...         "ceud_data_year": 2022,
    ...         "fuels": ["ELC", "NG", "DSL"],
    ...         "subsectors": {
    ...             "construction": {"skip": True},
    ...             "cement": {"fuels": ["ELC", "COAL"]},
    ...         },
    ...     }
    ... )
    >>> [s.short_desc() for s in config.modelled_subsectors()]
    ['PULP', 'SMELT', 'REFINING', 'CEMENT', 'CHEM', 'STEEL', 'OTH_MAN', 'FOR', 'MINING']
    >>> config.fuels_of(IndustrySubsector.Cement), config.fuels_of(IndustrySubsector.Mining)
    ([Electricity, Coal], [Electricity, NaturalGas, Diesel])
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["industry"]
    """Selects this sector in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. INDHR003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Model periods, the ones written. Inherited."""

    period_step: int = inherit()
    """Length of the last period, in years; the GDP of its end year scales its
    demands. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    # Demand projections
    gdp_scenario: CERScenario = inherit()
    """CER scenario of the GDP projections that scale the demands. Inherited."""

    gdp_projection_point: GDPProjectionPoint = inherit()
    """Year of each period at which GDP scales the demands. Inherited."""

    ceud_data_year: int
    """Year of the NRCan CEUD industry data read (energy use and fuel mix of each
    subsector). GDP projections are indexed to this year. Must be a year of the
    cached tables."""

    # Subsectors and fuels
    subsectors: dict[IndustrySubsector, IndustrySubsectorConfig] = Field(
        default_factory=dict
    )
    """Options of each subsector, one table each. Every subsector is modelled, with
    the sector's `fuels`, unless its table says otherwise; subsectors with no table
    take the defaults of `IndustrySubsectorConfig`."""

    fuels: list[CANOEFuel]
    """Fuels the subsector technologies consume, among `SUPPORTED_FUELS`, unless a
    subsector sets its own. In each province, the share of the energy use of a
    subsector's fuels not listed is spread over its fuels in proportion to their
    shares, and a fuel with no energy use is left out. "Other" (`OTH`) is not listed
    here, see `other_fuels`."""

    other_fuels: OtherFuelsTreatment = OtherFuelsTreatment.Free
    """What happens to the CEUD "Other" energy use of each subsector: deducted from
    its demand (`deduct`) or supplied for free (`free`). Applies to every
    subsector."""

    input_split_operator: OperatorCode = OperatorCode.GE
    """Operator of the input splits: lower bound (`ge`), upper bound (`le`) or exact
    share (`e`)."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods or regions this sector needs."""

    missing_data_behavior: ValidationBehavior = "warning"
    """What to do when data a modelled subsector needs is missing: energy use NRCan
    does not publish, or no StatCan share for an Atlantic province where the Atlantic
    table has energy use."""

    @field_validator("fuels")
    @classmethod
    def _check_fuels(cls, value: list[CANOEFuel]) -> list[CANOEFuel]:
        return _check_fuel_list(value)

    @model_validator(mode="after")
    def _check_some_subsector_modelled(self) -> Self:
        if not self.modelled_subsectors():
            raise ValueError("every industry subsector is skipped")
        return self

    def subsector_config(self, subsector: IndustrySubsector) -> IndustrySubsectorConfig:
        """Options of `subsector`: its table, or the defaults if it has none"""
        return self.subsectors.get(subsector, IndustrySubsectorConfig())

    def modelled_subsectors(self) -> list[IndustrySubsector]:
        """Subsectors not skipped, in the order of `IndustrySubsector`"""
        return [s for s in IndustrySubsector if not self.subsector_config(s).skip]

    def fuels_of(self, subsector: IndustrySubsector) -> list[CANOEFuel]:
        """Fuels of `subsector`: its own, or the sector's"""
        return self.subsector_config(subsector).fuels or self.fuels

    @override
    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=CANOESector.Industry,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    @override
    def run(self) -> CANOEModuleOutput:
        return build_industry(self)

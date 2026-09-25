from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, override

from canoe_schema.v4_0 import OperatorCode
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from canoe.canoe_objects.fuel_serving_tech import FuelGrouping
from canoe.commercial.build import build_commercial
from canoe.commercial.end_uses import CommercialEndUse
from canoe.commercial.technology_catalog import NewTechnology, technologies_for
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
from canoe.common.time_slices import AllTimeSlices, CANOETimeSliceSet

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class ComstockConfig(BaseModel):
    """NREL ComStock hourly profiles, used for the demand-specific distribution."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    building_types: list[str]
    """ComStock building types summed into the commercial profiles."""

    us_map: dict[CANOEProvince, str]
    """US state whose ComStock profiles each province takes."""


class SpaceConditioningEndUseConfig(BaseModel):
    """
    Space heating / space cooling.

    - Existing stock: one existing-capacity technology per fuel, estimated from CEUD
      energy use and AEO installed stock.
    - New capacity: the technologies in `new_technologies`, with parameters from the AEO
      technology menu (see `technology_catalog`). A technology listed under both space
      heating and space cooling is a single technology serving both demands.

    `new_technologies` options (`NewTechnology`), by end use they can serve:

    - space heating and space cooling: "air-source heat pump", "ground-source heat
      pump", "gas engine-driven heat pump", "residential-type gas heat pump"
    - space heating: "electric boiler", "electric resistance heater", "gas furnace",
      "gas boiler", "oil furnace", "oil boiler"
    - space cooling: "rooftop air conditioner", "wall/window air conditioner",
      "residential-type central air conditioner"

    Examples
    --------
    >>> heating = SpaceConditioningEndUseConfig(
    ...     existing_fuels=["NG", "ELC"],
    ...     new_technologies=["air-source heat pump", "gas furnace"],
    ... )
    >>> heating.new_technologies
    [<NewTechnology.AirSourceHeatPump: 'air-source heat pump'>, <NewTechnology.GasFurnace: 'gas furnace'>]
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    apply_weather_mapping: bool = False
    """Map the ComStock (US) hourly profiles to Canadian weather for the DSD."""

    existing_fuels: list[CANOEFuel]
    """Fuels we expect existing stock for. Missing ones are handled by
    `missing_data_behavior`."""

    new_technologies: list[NewTechnology] = []
    """Technologies that can be built to serve the end use (none by default)."""

    @field_validator("new_technologies")
    @classmethod
    def _check_no_duplicates(cls, value: list[NewTechnology]) -> list[NewTechnology]:
        duplicates = {t for t in value if value.count(t) > 1}
        if duplicates:
            raise ValueError(f"new_technologies listed more than once: {duplicates}")
        return value


class ElectrificationConfig(BaseModel):
    """
    Linear shift of the fuel shares of `other` towards electricity: by the end of the
    last model period, `factor` of the non-electric energy is switched 1:1 to electricity.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    factor: float = Field(ge=0, le=1)
    """Fraction (0-1) of the non-electric energy switched to electricity by the end of
    the last model period."""

    notes: str = ""
    """Appended to the input split notes."""


class OtherEndUseConfig(BaseModel):
    """
    Everything except space heating and cooling (lighting, equipment, water heating, ...).

    Demand is the CEUD secondary energy use minus space heating and cooling, served with
    efficiency 1 by new technologies with unlimited capacity.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    apply_weather_mapping: bool = False
    """Map the ComStock (US) hourly profiles to Canadian weather for the DSD."""

    fuels: list[CANOEFuel]
    """Fuels that serve the demand. Energy use of other fuels is left out of the
    demand."""

    min_fuel_share: float = Field(default=0.05, ge=0, lt=1)
    """Fuels below this share of a province's `other` energy use are dropped."""

    technology_grouping: FuelGrouping = FuelGrouping.Shared
    """`shared`: one technology, fuel mix fixed by input splits. `per_fuel`: one
    technology per fuel, fuel mix left to the model."""

    input_split_operator: OperatorCode = OperatorCode.LE
    """Operator of the input splits (`shared` only)."""

    electrification: ElectrificationConfig | None = None
    """Shift of the fuel mix towards electricity (`shared` only). Leave out for
    constant data-year fuel shares."""

    @model_validator(mode="after")
    def _check_shared_only_options(self) -> Self:
        if self.technology_grouping == FuelGrouping.PerFuel:
            shared_only = {"input_split_operator", "electrification"}
            used = shared_only & self.model_fields_set
            if used:
                raise ValueError(
                    f"{sorted(used)} only apply to technology_grouping = 'shared'"
                )
        return self


class EndUsesConfig(BaseModel):
    """
    One table per end use, `[end_uses."<end use name>"]` in TOML.
    An end use runs if and only if its table is present.
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", populate_by_name=True, use_attribute_docstrings=True
    )

    space_heating: SpaceConditioningEndUseConfig | None = Field(
        default=None, alias="space heating"
    )
    """`[end_uses."space heating"]`."""

    space_cooling: SpaceConditioningEndUseConfig | None = Field(
        default=None, alias="space cooling"
    )
    """`[end_uses."space cooling"]`."""

    other: OtherEndUseConfig | None = None
    """`[end_uses.other]`."""

    @model_validator(mode="after")
    def _check_new_technologies_serve_end_use(self) -> Self:
        for end_use, config in self.space_conditioning().items():
            valid = technologies_for(end_use)
            invalid = [t for t in config.new_technologies if t not in valid]
            if invalid:
                raise ValueError(
                    f"{[str(t.value) for t in invalid]} cannot serve "
                    + f"{end_use.get_full_name()}. Options: {[str(t.value) for t in valid]}"
                )
        return self

    def get(
        self, end_use: CommercialEndUse
    ) -> SpaceConditioningEndUseConfig | OtherEndUseConfig | None:
        return {
            CommercialEndUse.SpaceHeating: self.space_heating,
            CommercialEndUse.SpaceCooling: self.space_cooling,
            CommercialEndUse.Other: self.other,
        }[end_use]

    def enabled(self) -> list[CommercialEndUse]:
        """End uses with a table, in a fixed order"""
        return [eu for eu in CommercialEndUse if self.get(eu) is not None]

    def weather_mapping(self) -> dict[CommercialEndUse, bool]:
        return {
            eu: config.apply_weather_mapping
            for eu in CommercialEndUse
            if (config := self.get(eu)) is not None
        }

    def space_conditioning(
        self,
    ) -> dict[CommercialEndUse, SpaceConditioningEndUseConfig]:
        """Enabled space heating / cooling end uses"""
        return {
            eu: config
            for eu in CommercialEndUse
            if isinstance(config := self.get(eu), SpaceConditioningEndUseConfig)
        }

    def new_technologies(self) -> dict[NewTechnology, list[CommercialEndUse]]:
        """
        Selected new technologies -> end uses each one serves (space heating first).

        Examples
        --------
        >>> end_uses = EndUsesConfig.model_validate(
        ...     {
        ...         "space heating": {
        ...             "existing_fuels": ["ELC"],
        ...             "new_technologies": ["air-source heat pump", "electric boiler"],
        ...         },
        ...         "space cooling": {
        ...             "existing_fuels": ["ELC"],
        ...             "new_technologies": ["air-source heat pump"],
        ...         },
        ...     }
        ... )
        >>> for technology, served in end_uses.new_technologies().items():
        ...     print(technology.value, [str(end_use) for end_use in served])
        air-source heat pump ['SpaceHeating', 'SpaceCooling']
        electric boiler ['SpaceHeating']
        """
        selected: dict[NewTechnology, list[CommercialEndUse]] = {}
        for end_use, config in self.space_conditioning().items():
            for technology in config.new_technologies:
                selected.setdefault(technology, []).append(end_use)
        return selected


class CEUDConfig(BaseModel):
    """NRCan Comprehensive Energy Use Database (CEUD), commercial tables."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    data_year: int
    """Year of the NRCan CEUD data read: base-year energy use, existing stock and the
    year the GDP projections are indexed to."""

    space_cooling_tolerance: float = 0.05
    """Space cooling fuels below this share of a province's space cooling energy use
    are dropped."""


class AEOConfig(BaseModel):
    """EIA Annual Energy Outlook, Commercial Demand Module technology data."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    us_census_mapping: dict[CANOEProvince, str]
    """US census division whose technology data each province takes."""


class CANOECommercialConfig(InheritsFromBase, CANOEModule):
    """
    Commercial sector, `module_name = "commercial"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the sector TOML.
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["commercial"]
    """Selects this sector in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. COMHR003). Inherited."""

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

    end_uses: EndUsesConfig
    """End uses modelled, one table each."""

    # Demand projections
    gdp_scenario: CERScenario = inherit()
    """CER scenario of the GDP projections that scale the demands. Inherited."""

    gdp_projection_point: GDPProjectionPoint = inherit()
    """Year of each period at which GDP scales the demands. Inherited."""

    capacity_min_tolerance: float
    """Existing stock below this fraction of the total secondary energy consumption
    is filtered out."""

    # Runtime switches
    validation_behavior: Literal["error", "warning"] = "error"
    """What to do when the database lacks the periods, regions or time slices this
    sector needs."""

    missing_data_behavior: Literal["error", "warning"] = "warning"
    """What to do when the data of a requested fuel is missing."""

    # DSD parameters
    include_dsd: bool = True
    """Write the demand-specific distribution (hourly profile) of each demand."""

    dsd_time_slices: CANOETimeSliceSet = AllTimeSlices()
    """Time slices of the demand-specific distribution."""

    include_emissions: bool = False
    """Deprecated, must stay false: combustion emissions are handled by the fuels
    sector."""

    # Data sources
    comstock_config: ComstockConfig
    """NREL ComStock hourly profiles."""

    ceud_config: CEUDConfig
    """NRCan CEUD commercial tables."""

    aeo_config: AEOConfig
    """EIA AEO commercial technology data."""

    @model_validator(mode="after")
    def emissions_deprecated(self) -> "CANOECommercialConfig":
        if self.include_emissions:
            raise ValueError(
                "include_emissions is deprecated; Combustion emissions are handled by fuels sector."
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

    @property
    def period_end_years(self) -> dict[int, int]:
        """
        Model period -> the year it ends (the next year in `future_periods`).
        Projected data (GDP growth, electrification, ...) is taken at the period end.
        """
        return dict(zip(self.future_periods[:-1], self.future_periods[1:]))

    @override
    def get_dataset_code(self) -> str:
        # return f"COMHR{self.data_version}"
        return naming.get_dataset_code(
            sector=CANOESector.Commercial,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    @override
    def run(self) -> CANOEModuleOutput:
        return build_commercial(self)

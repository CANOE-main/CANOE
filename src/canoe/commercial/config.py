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
    building_types: list[str]
    us_map: dict[CANOEProvince, str]


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

    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportUnannotatedClassAttribute]

    # Map the Comstock (US) hourly profiles to Canadian weather for the DSD
    apply_weather_mapping: bool = False
    # Fuels we expect existing stock for. Missing ones are handled by `missing_data_behavior`
    existing_fuels: list[CANOEFuel]
    # Technologies that can be built to serve the end use (none by default)
    new_technologies: list[NewTechnology] = []

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

    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportUnannotatedClassAttribute]

    factor: float = Field(ge=0, le=1)
    # Appended to the input split notes
    notes: str = ""


class OtherEndUseConfig(BaseModel):
    """
    Everything except space heating and cooling (lighting, equipment, water heating, ...).

    Demand is the CEUD secondary energy use minus space heating and cooling, served with
    efficiency 1 by new technologies with unlimited capacity.
    """

    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportUnannotatedClassAttribute]

    # Map the Comstock (US) hourly profiles to Canadian weather for the DSD
    apply_weather_mapping: bool = False
    # Fuels that serve the demand. Energy use of other fuels is left out of the demand
    fuels: list[CANOEFuel]
    # Fuels below this share of a province's `other` energy use are dropped
    min_fuel_share: float = Field(default=0.05, ge=0, lt=1)
    # "shared": one technology, fuel mix fixed by input splits
    # "per_fuel": one technology per fuel, fuel mix left to the model
    technology_grouping: FuelGrouping = FuelGrouping.Shared
    # Operator of the input splits ("shared" only)
    input_split_operator: OperatorCode = OperatorCode.LE
    # Leave out for constant base-year fuel shares ("shared" only)
    electrification: ElectrificationConfig | None = None

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

    model_config = ConfigDict(extra="forbid", populate_by_name=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    space_heating: SpaceConditioningEndUseConfig | None = Field(
        default=None, alias="space heating"
    )
    space_cooling: SpaceConditioningEndUseConfig | None = Field(
        default=None, alias="space cooling"
    )
    other: OtherEndUseConfig | None = None

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
    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    data_year: int
    """Year of the NRCan CEUD data read: base-year energy use, existing stock and the
    year the GDP projections are indexed to."""

    space_cooling_tolerance: float = 0.05


class AEOConfig(BaseModel):
    us_census_mapping: dict[CANOEProvince, str]


class CANOECommercialConfig(InheritsFromBase, CANOEModule):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)  # pyright: ignore[reportUnannotatedClassAttribute]
    module_name: Literal["commercial"]

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()

    # File paths
    database_file: Path = inherit()
    data_cache_config: GoldConnectorConfig = inherit()

    # Model scope
    future_periods: list[int] = inherit()
    provinces: list[CANOEProvince] = inherit()
    end_uses: EndUsesConfig

    # Demand projections
    gdp_scenario: CERScenario = inherit()
    gdp_projection_point: GDPProjectionPoint = inherit()

    # Filter out secondary energy consumption below this fraction of total
    capacity_min_tolerance: float

    # Runtime switches
    validation_behavior: Literal["error", "warning"] = "error"
    missing_data_behavior: Literal["error", "warning"] = "warning"

    # DSD parameters
    include_dsd: bool = True
    dsd_time_slices: CANOETimeSliceSet = AllTimeSlices()

    # Combustion emissions (CO2, CH4, N2O) of the fuels, from EPA emission factors.
    # CO2-equivalents are added by the central emissions step.
    include_emissions: bool = False

    # Data sources
    comstock_config: ComstockConfig
    ceud_config: CEUDConfig

    # # AEO
    aeo_config: AEOConfig

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

"""
Configuration of the CANOE residential sector, one TOML file per run (see
`configuration/residential-default.toml`).

The residential sector has eleven end uses (`ResidentialEndUse`), each a demand:
space heating, space cooling, water heating, lighting and seven appliances. Each end
use is served by the existing stock of the NRCan CEUD (one technology per system
type, with existing capacity) and, optionally, by new technologies from the AEO
residential technology menu (`NewTechnology`). The demands are the base-year output
of the existing stock, projected with population (or GDP).

End uses come in five tables (space heating, space cooling, water heating,
lighting, appliances); a table that is left out is not modelled.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, override

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from canoe.common import (
    CANOEModule,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.census_divisions import USCensusDivision
from canoe.common.gdp import CERScenario, GDPProjectionPoint
from canoe.common.time_slices import AllTimeSlices, CANOETimeSliceSet
from canoe.common.validation import ValidationBehavior
from canoe.residential.build import build_residential
from canoe.residential.demand import DemandDriver
from canoe.residential.end_uses import ResidentialEndUse
from canoe.residential.technology_catalog import (
    NewTechnology,
    technologies_for,
)

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class _EndUseConfig(BaseModel):
    """Options shared by every end use table."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = ()
    """End uses of the table, the ones its new technologies can serve."""

    new_technologies: list[NewTechnology] = []
    """Technologies that can be built to serve the end use (none by default), among
    those that serve it (see `technology_catalog`)."""

    @field_validator("new_technologies")
    @classmethod
    def _check_new_technologies(cls, value: list[NewTechnology]) -> list[NewTechnology]:
        duplicates = {t for t in value if value.count(t) > 1}
        if duplicates:
            raise ValueError(f"new_technologies listed more than once: {duplicates}")
        valid = technologies_for(cls.END_USES)
        invalid = [t for t in value if t not in valid]
        if invalid:
            raise ValueError(
                f"{[t.value for t in invalid]} cannot serve "
                + f"{', '.join(e.value for e in cls.END_USES)}. "
                + f"Options: {[t.value for t in valid]}"
            )
        return value


class SpaceHeatingConfig(_EndUseConfig):
    """
    Space heating, `[end_uses."space heating"]`. A heat pump listed under both space
    heating and space cooling is a single technology serving both demands.

    Examples
    --------
    >>> SpaceHeatingConfig(new_technologies=["natural gas furnace"])
    SpaceHeatingConfig(new_technologies=[<NewTechnology.NaturalGasFurnace: 'natural gas furnace'>], apply_weather_mapping=True)
    """

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = (
        ResidentialEndUse.SpaceHeating,
    )

    apply_weather_mapping: bool = True
    """Map the ResStock (US) hourly profiles to Canadian weather for the DSD."""


class SpaceCoolingConfig(_EndUseConfig):
    """Space cooling, `[end_uses."space cooling"]`."""

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = (
        ResidentialEndUse.SpaceCooling,
    )

    apply_weather_mapping: bool = True
    """Map the ResStock (US) hourly profiles to Canadian weather for the DSD."""


class WaterHeatingConfig(_EndUseConfig):
    """Water heating, `[end_uses."water heating"]`."""

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = (
        ResidentialEndUse.WaterHeating,
    )


class LightingConfig(_EndUseConfig):
    """Lighting, `[end_uses.lighting]`. Demand and capacity are in light (Glm, Glmy)."""

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = (ResidentialEndUse.Lighting,)

    annual_capacity_factor: float = Field(default=0.0667, gt=0, le=1)
    """Share of the year lamps are on: 1.6 hours a day, the US national average
    (DOE, 2012). Sets the lamps' lifetime in years from their life in hours."""


class AppliancesConfig(_EndUseConfig):
    """
    The seven appliance end uses, `[end_uses.appliances]`. Demand and capacity are in
    appliances in use (Munity, Munit).
    """

    END_USES: ClassVar[tuple[ResidentialEndUse, ...]] = ResidentialEndUse.appliances()

    annual_capacity_factor: float = Field(default=0.15, gt=0, le=1)
    """Arbitrary share of the year appliances run, so the existing stock can meet the
    peak demand. The demand is the existing stock times this factor."""


class EndUsesConfig(BaseModel):
    """
    One table per group of end uses, `[end_uses."<name>"]` in TOML. A group is
    modelled if and only if its table is present.

    Examples
    --------
    >>> end_uses = EndUsesConfig.model_validate(
    ...     {"space heating": {}, "appliances": {"annual_capacity_factor": 0.2}}
    ... )
    >>> end_uses.enabled()
    [SpaceHeating, Refrigerators, Freezers, DishWashers, ClothesWashers, ClothesDryers, CookingRanges, OtherAppliances]
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", populate_by_name=True, use_attribute_docstrings=True
    )

    space_heating: SpaceHeatingConfig | None = Field(
        default=None, alias="space heating"
    )
    """`[end_uses."space heating"]`."""

    space_cooling: SpaceCoolingConfig | None = Field(
        default=None, alias="space cooling"
    )
    """`[end_uses."space cooling"]`."""

    water_heating: WaterHeatingConfig | None = Field(
        default=None, alias="water heating"
    )
    """`[end_uses."water heating"]`."""

    lighting: LightingConfig | None = None
    """`[end_uses.lighting]`."""

    appliances: AppliancesConfig | None = None
    """`[end_uses.appliances]`."""

    @model_validator(mode="after")
    def _check_some_end_use(self) -> Self:
        if not self.tables():
            raise ValueError("no end use table: at least one end use is needed")
        return self

    def tables(self) -> list[_EndUseConfig]:
        """The tables present, in a fixed order"""
        tables = [
            self.space_heating,
            self.space_cooling,
            self.water_heating,
            self.lighting,
            self.appliances,
        ]
        return [table for table in tables if table is not None]

    def enabled(self) -> list[ResidentialEndUse]:
        """End uses modelled, in the order of `ResidentialEndUse`"""
        modelled = {end_use for table in self.tables() for end_use in table.END_USES}
        return [end_use for end_use in ResidentialEndUse if end_use in modelled]

    def new_technologies(self) -> dict[NewTechnology, list[ResidentialEndUse]]:
        """
        Selected new technologies -> end uses each one serves: those of the tables it
        is listed in.

        Examples
        --------
        >>> end_uses = EndUsesConfig.model_validate(
        ...     {
        ...         "space heating": {
        ...             "new_technologies": ["air-source heat pump"]
        ...         },
        ...         "space cooling": {
        ...             "new_technologies": ["air-source heat pump"]
        ...         },
        ...     }
        ... )
        >>> end_uses.new_technologies()
        {<NewTechnology.AirSourceHeatPump: 'air-source heat pump'>: [SpaceHeating, SpaceCooling]}
        """
        selected: dict[NewTechnology, list[ResidentialEndUse]] = {}
        for table in self.tables():
            for technology in table.new_technologies:
                served = [e for e in technology.end_uses() if e in table.END_USES]
                selected.setdefault(technology, []).extend(served)
        return selected

    def weather_mapping(self) -> dict[ResidentialEndUse, bool]:
        """Whether the DSD of each modelled end use is mapped to Canadian weather"""
        mapped = {
            table.END_USES[0]
            for table in (self.space_heating, self.space_cooling)
            if table is not None and table.apply_weather_mapping
        }
        return {end_use: end_use in mapped for end_use in self.enabled()}


class CANOEResidentialConfig(InheritsFromBase, CANOEModule):
    """
    Residential sector, `module_name = "residential"`.

    Fields marked as inherited take their value from `[compiler.base]` unless set in
    the sector TOML.
    """

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", arbitrary_types_allowed=True, use_attribute_docstrings=True
    )

    module_name: Literal["residential"]
    """Selects this sector in the pipeline."""

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        "database_file": lambda base: Path(base.db_output_dir),
        "demand_projection_point": lambda base: base.gdp_projection_point,
    }

    # Identity
    data_version: str = inherit()
    """Version in the data set codes (e.g. RESHR003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Model periods, the ones written. Inherited."""

    period_step: int = inherit()
    """Length of the last period and years between existing vintages. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    end_uses: EndUsesConfig
    """End uses modelled, one table per group."""

    # Demand projections
    ceud_data_year: int
    """Year of the NRCan CEUD residential data read (energy use, stock, efficiencies):
    the base year of the demands and existing capacity. Must be a year of the data."""

    demand_driver: DemandDriver = DemandDriver.Population
    """Series that projects the base-year demands: provincial population or national
    GDP."""

    demand_projection_point: GDPProjectionPoint = inherit()
    """Year of each period at which the demand driver is read. Inherited from
    `gdp_projection_point`."""

    gdp_scenario: CERScenario = inherit()
    """CER scenario of the GDP projections, with `demand_driver = "gdp"`. Inherited."""

    # Costs
    model_currency_year: int = inherit()
    """Year of the Canadian dollars the costs are written in. Inherited."""

    # Existing stock
    existing_capacity_tolerance: float = Field(default=0.1, ge=0)
    """Existing technologies whose existing capacity in a province is below this
    (kunit, Munit or Glm) are left out there."""

    # Data source mappings
    resstock_us_states: dict[CANOEProvince, str]
    """US state whose ResStock hourly profiles each province takes."""

    aeo_census_divisions: dict[CANOEProvince, USCensusDivision]
    """US census division whose AEO technology parameters each province takes."""

    # Demand-specific distribution
    include_dsd: bool = True
    """Write the demand-specific distribution (hourly profile) of each demand."""

    dsd_time_slices: CANOETimeSliceSet = AllTimeSlices()
    """Time slices of the demand-specific distribution."""

    dsd_tolerance: float = Field(default=0.02, ge=0, lt=1)
    """Hours of a profile below this fraction of its mean are set to 0 (fewer
    rows)."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods, regions or time slices this
    sector needs."""

    missing_data_behavior: ValidationBehavior = "warning"
    """What to do when data a modelled end use needs is missing."""

    @model_validator(mode="after")
    def _check_province_mappings(self) -> Self:
        for name in ("resstock_us_states", "aeo_census_divisions"):
            mapping: dict[CANOEProvince, Any] = getattr(self, name)
            missing = [p.short() for p in self.provinces if p not in mapping]
            if missing:
                raise ValueError(f"{name} has no entry for {missing}")
        return self

    @override
    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=CANOESector.Residential,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    @override
    def run(self) -> CANOEModuleOutput:
        return build_residential(self)

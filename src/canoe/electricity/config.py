"""
Configuration of the CANOE electricity module, one TOML file referenced from the
pipeline (`[compiler] electricity = "configuration/electricity-default.toml"`).

The electricity module supplies the electricity the sectors import. It runs after the
sectors, from their electricity imports: it delivers `E_elc_dem` to each sector's
`<S>_elc` (`E_<S>_ELC`), and builds the grid that produces it (generation, storage,
trade between provinces and with the US, reliability). The fuels its generators burn
are declared as fuel imports, supplied by the fuel module, which runs after it.

The grid itself always runs; each table says which of its parts are left out.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from canoe.common import (
    CANOEFuelImport,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.gdp import GDPProjectionPoint
from canoe.common.periods import ProjectionPoint
from canoe.common.validation import ValidationBehavior
from canoe.electricity.build import build_electricity
from canoe.electricity.catalogue import (
    CCSRetrofit,
    GenerationTechnology,
    StorageTechnology,
)

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


def _check_unique[T](value: list[T]) -> list[T]:
    duplicates = {v for v in value if value.count(v) > 1}
    if duplicates:
        raise ValueError(f"listed more than once: {sorted(map(str, duplicates))}")
    return value


class SourceYears(BaseModel):
    """
    Years of the data sources, `[source_years]` in TOML. Each source keeps its own
    year so the previous module's data can be reproduced; they are to be harmonized
    into one weather year once the cache has every source for the same year.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    coders_hourly: int
    """Year of the CODERS hourly provincial demand and interprovincial and
    international transfers (US export demand and its profile, boundary interties,
    exogenous demand profile, net load of the capacity credits)."""

    ieso_hourly: int
    """Year of the IESO hourly generator output (Ontario wind, solar and hydro
    capacity factors)."""

    statcan_monthly_hydro: int
    """Year of StatCan Table 25-10-0015-01 (monthly hydro generation, hydro capacity
    factors outside Ontario)."""

    renewables_ninja: int
    """Year of the renewables.ninja profiles (existing wind and solar capacity factors
    outside Ontario)."""

    ieso_reliability_outlook: int
    """Year of the IESO Reliability Outlook (Table 4.1, capability at summer peak by
    fuel: capacity credits and reserve capacity derates)."""

    atb_currency: int = 2022
    """Year of the US dollars of NREL ATB 2024 costs, 2022. The previous module used
    2021 (see `ELECTRICITY_MODULE_BUGS.md`); set it to reproduce its databases."""

    coders_currency: int = 2020
    """Year of the Canadian dollars of CODERS `generation_generic` costs. The table
    gives none; the previous module took 2020."""


class GenerationConfig(BaseModel):
    """Generators, `[generation]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    skip_existing: bool = False
    """Leave out the existing generators (`-EXS`), the CODERS fleet."""

    existing_capacity_threshold: float = Field(default=0.001, ge=0)
    """Smallest existing capacity kept for a (region, technology, vintage), GW."""

    cogeneration_floor: float = Field(default=0.95, ge=0, le=1)
    """Lower bound of the annual output of existing cogeneration, as a share of its
    historical output (the upper bound). Below 1 to give the solver slack."""

    capacity_factor_tolerance: float = Field(default=0.01, ge=0, lt=1)
    """Capacity factors below this are set to 0 (noise in the weather data)."""

    new_technologies: list[GenerationTechnology]
    """New generators the model can build (`-NEW`); empty for none. Only those with
    data (see `GenerationTechnology.can_be_new`). Solar and onshore wind come as
    resource bins (`E_SOL_PV-NEW-<n>`, `E_WND_ON-NEW-<n>`)."""

    ccs_retrofits: list[CCSRetrofit]
    """Carbon capture retrofits the model can build on coal and natural gas combined
    cycle generators; empty for none."""

    ccs_retrofit_heat_rates: dict[GenerationTechnology, float] = Field(
        default_factory=lambda: {
            GenerationTechnology.Coal: 8.49,
            GenerationTechnology.NaturalGasCC: 6.196,
        }
    )
    """Heat rate (MMBtu of fuel per MWh) of the generators a CCS retrofit treats, for
    the CO2 it captures: one value for all the plant vintages whose output the
    retrofit takes. Defaults: NREL ATB 2024, 2022 new plant (`Coal-new`, `NG 2-on-1
    Combined Cycle (H-Frame)`). TODO: replace with a source for the existing fleet's
    heat rates."""

    @field_validator("new_technologies", "ccs_retrofits")
    @classmethod
    def _check_technologies[T](cls, value: list[T]) -> list[T]:
        return _check_unique(value)

    @field_validator("new_technologies")
    @classmethod
    def _check_new_data(
        cls, value: list[GenerationTechnology]
    ) -> list[GenerationTechnology]:
        without_data = [t.value for t in value if not t.can_be_new()]
        if without_data:
            raise ValueError(
                f"no data to build new {without_data}: new technologies need NREL ATB "
                + "costs, and capacity factors if they burn no fuel (only solar and "
                + "onshore wind have them)"
            )
        return value

    @model_validator(mode="after")
    def _check_retrofitted_generators(self) -> Self:
        without_heat_rate = sorted(
            {
                r.get_generator().value
                for r in self.ccs_retrofits
                if not self.ccs_retrofit_heat_rates.get(r.get_generator(), 0) > 0
            }
        )
        if without_heat_rate:
            raise ValueError(
                f"CCS retrofits of {without_heat_rate} need a positive heat rate in "
                + "ccs_retrofit_heat_rates"
            )
        if not self.skip_existing:
            return self
        orphans = [
            r.value
            for r in self.ccs_retrofits
            if r.get_generator() not in self.new_technologies
        ]
        if orphans:
            raise ValueError(
                f"CCS retrofits {orphans} apply to generators that are not modelled: "
                + "keep the existing generators or add theirs to new_technologies"
            )
        return self


class StorageConfig(BaseModel):
    """Storage, `[storage]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    skip_existing: bool = False
    """Leave out the existing storage (`-EXS`), from CODERS."""

    new_technologies: list[StorageTechnology]
    """Storage the model can build (`-NEW`); empty for none. Only those with NREL
    ATB costs (see `StorageTechnology.can_be_new`)."""

    battery_round_trip_efficiency: float = Field(default=0.85, gt=0, le=1)
    """Electricity out per unit stored, batteries. The default follows NREL ATB."""

    pumped_hydro_round_trip_efficiency: float = Field(default=0.80, gt=0, le=1)
    """Electricity out per unit stored, pumped hydro. The default follows NREL ATB."""

    @field_validator("new_technologies")
    @classmethod
    def _check_technologies(
        cls, value: list[StorageTechnology]
    ) -> list[StorageTechnology]:
        without_data = [t.value for t in value if not t.can_be_new()]
        if without_data:
            raise ValueError(
                f"no data to build new {without_data}: new storage needs NREL ATB "
                + "costs"
            )
        return _check_unique(value)


class TradeConfig(BaseModel):
    """Interties, `[trade]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    skip_endogenous: bool = False
    """Leave out the interties between modelled provinces (`E_INT`), whose flows the
    model decides."""

    skip_boundary: bool = False
    """Leave out the interties with the US, fixed to historical flows: imports as a
    generator (`E_INT_IN-USA`), exports as a demand (`E_INT_OUT-USA`)."""

    reproduce_previous_intertie_losses: bool = False
    """Take the system (transmission and distribution) losses of the sending province
    on the interties and exports, as the previous module did. The electricity then
    pays distribution losses it does not go through, twice on the interties (again
    in the receiving province's grid; see `ELECTRICITY_MODULE_BUGS.md`). Off: their
    transmission losses only."""


class ReliabilityConfig(BaseModel):
    """Reserve margin, `[reliability]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    skip: bool = False
    """Leave out the planning reserve margin and what counts towards it: capacity
    credits (static reserve margin) and reserve capacity derates (dynamic). Temoa's
    `reserve_margin` setting picks which one applies."""

    ieso_peak_type: Literal["Firm", "Planned"] = "Firm"
    """Capability at summer peak of the IESO Reliability Outlook the capacity credits
    and derates are read from: firm (resources under contract) or planned."""

    reproduce_previous_hydro_storage_derate: bool = False
    """Derate the monthly hydro reservoir (`E_HYD_MLY-EXS`) as the previous module
    did. In dynamic mode Temoa counts a storage technology's discharge in each time
    slice times its derate; that discharge is already limited by the water stored,
    so the derate counts the low availability twice (see
    `ELECTRICITY_MODULE_BUGS.md`). Off: the reservoir gets no derate (Temoa's 1)."""


class CANOEElectricityConfig(InheritsFromBase):
    """
    Electricity module.

    Not an end-use sector: it runs once all sectors have run, with their electricity
    imports (see `run`). Fields marked as inherited take their value from
    `[compiler.base]` unless set in the module's TOML.

    Examples
    --------
    >>> config = CANOEElectricityConfig.model_validate(
    ...     {
    ...         "data_version": "001",
    ...         "database_file": "canoe.sqlite",
    ...         "data_cache_config": {"cache_date": "2026-08-10"},
    ...         "future_periods": [2025, 2030],
    ...         "period_step": 5,
    ...         "provinces": ["ON", "QC"],
    ...         "price_projection_point": "period_end",
    ...         "gdp_projection_point": "period_end",
    ...         "model_currency_year": 2020,
    ...         "source_years": {
    ...             "coders_hourly": 2018,
    ...             "ieso_hourly": 2018,
    ...             "statcan_monthly_hydro": 2018,
    ...             "renewables_ninja": 2018,
    ...             "ieso_reliability_outlook": 2025,
    ...         },
    ...         "generation": {
    ...             "new_technologies": ["ng_cc", "wind_onshore"],
    ...             "ccs_retrofits": ["ng_ccs_retrofit_90"],
    ...         },
    ...         "storage": {"skip_existing": True, "new_technologies": []},
    ...     }
    ... )
    >>> config.get_dataset_code()
    'ELCHR001'
    >>> config.exogenous_demand, config.storage.skip_existing, config.trade.skip_boundary
    (False, True, False)
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
    """Version in the data set codes (e.g. ELCHR003). Inherited."""

    # File paths
    database_file: Path = inherit()
    """Database written to. Inherited from `db_output_dir`."""

    data_cache_config: GoldConnectorConfig = inherit()
    """Location and date of the data lake cache. Inherited."""

    # Model scope
    future_periods: list[int] = inherit()
    """Model periods, the ones written. Inherited."""

    period_step: int = inherit()
    """Length of the last period, in years. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions written. Inherited."""

    # Costs
    price_projection_point: ProjectionPoint = inherit()
    """Year of each period at which projected costs (e.g. transmission and
    distribution) are read. Inherited."""

    model_currency_year: int = inherit()
    """Year of the Canadian dollars costs are written in. Inherited."""

    # Data sources
    source_years: SourceYears
    """Year of each data source."""

    atb_scenario: Literal["Advanced", "Moderate", "Conservative"] = "Moderate"
    """NREL ATB scenario of the efficiencies and costs taken from the ATB."""

    # Demand
    exogenous_demand: bool = False
    """Add the CODERS annual provincial demand forecast (read at
    `gdp_projection_point` of each period, with the hourly profile of
    `source_years.coders_hourly`) as an electricity demand (`E_D_elc`). Off by
    default: the sectors' electricity imports are the demand, and alongside them it
    counts their electricity use twice. Meant for runs of the electricity module on
    its own."""

    exogenous_demand_profile_tolerance: float = Field(default=0.02, ge=0, lt=1)
    """Hours of the exogenous demand profile below this share of the average hour are
    set to 0 (gaps and noise in the data)."""

    gdp_projection_point: GDPProjectionPoint = inherit()
    """Year of each period at which the exogenous demand forecast is read, as the
    sectors' demand projections. Inherited."""

    # Components
    generation: GenerationConfig
    """Existing and new generators and carbon capture retrofits."""

    storage: StorageConfig
    """Existing and new storage."""

    trade: TradeConfig = TradeConfig()
    """Interties between provinces and with the US."""

    reliability: ReliabilityConfig = ReliabilityConfig()
    """Planning reserve margin, capacity credits and reserve capacity derates."""

    # Runtime switches
    validation_behavior: ValidationBehavior = "error"
    """What to do when the database lacks the periods or regions this module
    needs."""

    missing_data_behavior: ValidationBehavior = "warning"
    """What to do when data a modelled component needs is missing."""

    def get_dataset_code(self) -> str:
        return naming.get_dataset_code(
            sector=CANOESector.Electricity,
            resolution_str="HR",
            version_code=self.data_version,
            province=None,
        )

    def run(self, fuel_imports: list[CANOEFuelImport]) -> CANOEModuleOutput:
        """Supply the electricity in `fuel_imports`, the fuel imports declared by all
        the sectors (other fuels are the fuel module's)."""
        return build_electricity(self, fuel_imports)

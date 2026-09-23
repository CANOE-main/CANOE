from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, override

from canoe_schema.v4_0 import OperatorCode
from pydantic import BaseModel, ConfigDict, Field, model_validator

from canoe.canoe_objects.fuel_serving_tech import FuelGrouping
from canoe.commercial.build import build_commercial
from canoe.common import (
    CANOEFuel,
    CANOEModule,
    CANOEModuleOutput,
    CANOEProvince,
    CANOESector,
    GoldConnectorConfig,
    naming,
)
from canoe.common.time_slices import AllTimeSlices, CANOETimeSliceSet

from ..common.module_inheritance import InheritsFromBase, inherit
from ..initializer import CANOEBaseConfig


class CommercialEndUse(StrEnum):
    SpaceHeating = "heating"
    SpaceCooling = "cooling"
    Other = "other"

    @classmethod
    @override
    def _missing_(cls, value: Any):
        if isinstance(value, str) and value in cls.__members__:
            return cls.__members__[value]
        for member in cls:
            if value == member.get_full_name():
                return member
        return None

    def get_full_name(self):
        _NAMES = {
            "heating": "space heating",
            "cooling": "space cooling",
            "other": "other",
        }
        return _NAMES[self.value]

    def get_short_name(self):
        _NAMES = {
            "heating": "sph",
            "cooling": "spc",
            "other": "oth",
        }
        return _NAMES[self.value]

    @override
    def __str__(self):
        return str(self.name)


class ComstockConfig(BaseModel):
    building_types: list[str]
    us_map: dict[CANOEProvince, str]


class ExistingStockEndUseConfig(BaseModel):
    """
    Space heating / space cooling: one existing-capacity technology per fuel,
    estimated from CEUD energy use and AEO installed stock.
    """

    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportUnannotatedClassAttribute]

    # Map the Comstock (US) hourly profiles to Canadian weather for the DSD
    apply_weather_mapping: bool = False
    # Fuels we expect existing stock for. Missing ones are handled by `missing_data_behavior`
    existing_fuels: list[CANOEFuel]


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

    space_heating: ExistingStockEndUseConfig | None = Field(
        default=None, alias="space heating"
    )
    space_cooling: ExistingStockEndUseConfig | None = Field(
        default=None, alias="space cooling"
    )
    other: OtherEndUseConfig | None = None

    def get(
        self, end_use: CommercialEndUse
    ) -> ExistingStockEndUseConfig | OtherEndUseConfig | None:
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

    def existing_stock(self) -> dict[CommercialEndUse, ExistingStockEndUseConfig]:
        """Enabled end uses modelled with existing-stock technologies"""
        return {
            eu: config
            for eu in CommercialEndUse
            if isinstance(config := self.get(eu), ExistingStockEndUseConfig)
        }


class CEUDConfig(BaseModel):
    base_year: int
    space_cooling_tolerance: float = 0.05


class AEOConfig(BaseModel):
    us_census_mapping: dict[CANOEProvince, str]


class CANOECommercialConfig(InheritsFromBase, CANOEModule):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)  # pyright: ignore[reportUnannotatedClassAttribute]
    module_name: Literal["commercial"]

    # Fields inherited as-is need no entry here; only renames/derivations do.
    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[CANOEBaseConfig], Any]]] = {
        # "province_list": lambda base: [p.short() for p in base.provinces],
        "database_file": lambda base: Path(base.db_output_dir),
    }

    # Identity
    data_version: str = inherit()

    # File paths
    database_file: Path = inherit()
    data_cache_config: GoldConnectorConfig = inherit()
    # excel_template: str
    # excel_output: str
    # input_files: str = "input_files/"
    # cache_dir: str = "data_cache/"

    # Model scope
    future_periods: list[int] = inherit()
    provinces: list[CANOEProvince] = inherit()
    base_year: int
    end_uses: EndUsesConfig
    # period_step: int
    # timezone: str

    # Filter out secondary energy consumption below this fraction of total
    capacity_min_tolerance: float

    # Runtime switches
    validation_behavior: Literal["error", "warning"] = "error"
    missing_data_behavior: Literal["error", "warning"] = "warning"

    # DSD parameters
    include_dsd: bool = True
    dsd_time_slices: CANOETimeSliceSet = AllTimeSlices()

    # force_download: bool = False
    # show_plots: bool = True
    # clone_to_xlsx: bool = False
    # force_generate_weather_maps: bool = False

    # # EPA emissions
    include_emissions: bool = False
    # epa_year: int
    # epa_url: str
    # epa_reference: str
    EPA_emission_commodity: str = ""
    # emission_activity_units: str

    # Data sources
    comstock_config: ComstockConfig
    ceud_config: CEUDConfig

    # # Parameters
    # sec_tolerance: float
    # other_electrification_factor: float
    # cef_note: str
    # cef_reference: str
    # weather_year: int

    # # GDP
    # gdp_url: str
    # gdp_scenario: str = "Global Net-zero"
    # gdp_variable: str = "Real Gross Domestic Product ($2012 Millions)"
    # gdp_data_year: int
    # gdp_reference: str

    # # Population
    # population_m_scenario: str = "Projection scenario M1: medium-growth"
    # pop_reference: str

    # # AEO
    # aeo_installed_year: int
    # aeo_reference: str
    aeo_config: AEOConfig

    # # NRCan
    # nrcan_url: str
    # nrcan_reference: str

    # # Currency
    # final_currency: str
    # final_currency_year: int
    # inflation_index: str
    # aeo_currency_year: int
    # aeo_currency: str

    # # Nested config
    # comstock: ComstockConfig
    # weather: WeatherConfig
    # conversion_factors: ConversionFactors

    # # DQ profiles
    # dq_demands: DataQualityProfile
    # dq_efficiency: DataQualityProfile
    # dq_existing_capacity: DataQualityProfile
    # dq_costs: DataQualityProfile
    # dq_emissions: DataQualityProfile
    # dq_capacity_factor: DataQualityProfile
    # dq_fuel_splits: DataQualityProfile
    # dq_lifetime: DataQualityProfile

    # # Runtime data — populated by _load_data(), not sourced from TOML
    # regions: Optional[pd.DataFrame] = None
    # new_techs: Optional[pd.DataFrame] = None
    # existing_techs: Optional[pd.DataFrame] = None
    # import_techs: Optional[pd.DataFrame] = None
    # fuel_commodities: Optional[pd.DataFrame] = None
    # end_use_demands: Optional[pd.DataFrame] = None
    # time: Optional[pd.DataFrame] = None
    # aeo_cdm: Optional[pd.DataFrame] = None
    # gdp_index: Optional[pd.DataFrame] = None
    # populations: Optional[dict] = None
    # all_techs: list[str] = Field(default_factory=list)
    # rninja_api: str = ""
    # sources: dict = Field(default_factory=dict)
    # data_ids: set = Field(default_factory=set)

    # @property
    # def model_periods(self) -> list[int]:
    #     return sorted(self.future_periods)

    # @property
    # def model_regions(self) -> list[str]:
    #     return sorted(self.province_list)

    # @property
    # def database_file(self) -> str:
    #     return str(Path(self.db_dir) / self.sqlite_database)

    # @property
    # def excel_template_file(self) -> str:
    #     return self.input_files + self.excel_template

    # @property
    # def excel_target_file(self) -> str:
    #     return str(Path(self.db_dir) / self.excel_output)

    # def data_id(self, text: str = '') -> str:
    #     id = f"{self.data_id_prefix}{text}{self.data_version}"
    #     self.data_ids.add(id)
    #     return id

    # @classmethod
    # def validate_from_toml(cls, toml_dir: str = "input_files") -> "CANOECommercialConfig":
    #     path = Path(toml_dir) / "params.toml"
    #     with open(path, "rb") as f:
    #         raw = tomllib.load(f)
    #     cfg = cls.model_validate(raw)
    #     cfg._load_data()
    #     return cfg

    # def _load_data(self) -> None:
    #     if not os.path.exists(self.cache_dir):
    #         os.mkdir(self.cache_dir)

    #     self.regions = pd.read_csv(self.input_files + "regions.csv", index_col=0)
    #     self.new_techs = pd.read_csv(self.input_files + "new_technologies.csv", index_col=0)
    #     self.existing_techs = pd.read_csv(self.input_files + "existing_technologies.csv", index_col=0)
    #     self.import_techs = pd.read_csv(self.input_files + "import_technologies.csv", index_col=0)
    #     self.fuel_commodities = pd.read_csv(self.input_files + "fuel_commodities.csv", index_col=0)
    #     self.end_use_demands = pd.read_csv(self.input_files + "end_use_demands.csv", index_col=0)
    #     self.time = pd.read_csv(self.input_files + "time.csv", index_col=0)

    #     self.new_techs = self.new_techs.loc[self.new_techs["include_new"]]
    #     self.all_techs = [*self.new_techs.index.values, *self.existing_techs.index.values]

    #     self.aeo_cdm = data_scraper.fetch_aeo_data(
    #         aeo_file=self.input_files + "ktekx.xlsx",
    #         indexing_file=self.input_files + "aeo_cdm_indexing.csv",
    #     )

    #     self.populations = data_scraper.fetch_population_projections(
    #         regions_df=self.regions,
    #         cache_dir=self.cache_dir,
    #         force_download=self.force_download,
    #     )

    #     self.gdp_index = data_scraper.fetch_gdp_projections(
    #         gdp_url=self.gdp_url,
    #         base_year=self.base_year,
    #         cache_dir=self.cache_dir,
    #         force_download=self.force_download,
    #     )

    #     try:
    #         with open("input_files/rninja_api_token.txt") as token_file:
    #             self.rninja_api = token_file.read()
    #     except FileNotFoundError:
    #         self.rninja_api = "WARNING: rninja_api_token.txt not found"

    #     from canoe_commercial.sources import build_sources
    #     self.sources = build_sources(self)

    #     print("Instantiated setup config.\n")

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

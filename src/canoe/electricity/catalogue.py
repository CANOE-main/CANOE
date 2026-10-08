"""
Technologies of the electricity module and where they sit on the grid.

The grid is a chain of three commodities, from bulk transmission to the end-use
sectors:

    E_elc_tx --E_ELC_TX_to_DX--> E_elc_dx --E_ELC_DX_to_DEM--> E_elc_dem

Generators inject into the transmission (`tx`) or distribution (`dx`) level, storage
takes from and returns to the transmission level, and each sector draws from
`E_elc_dem`. The enums replace the technology CSVs of the previous module
(`generator_technologies.csv`, `storage_technologies.csv`,
`ccs_retrofit_technologies.csv`); data source names (CODERS, ATB) are added as methods
in the steps that read them.
"""

from enum import StrEnum

from canoe.common import CANOEFuel


class GridLevel(StrEnum):
    """Level of the grid a technology injects into."""

    Transmission = "tx"
    """Bulk transmission, `E_elc_tx`: line losses to distribution apply."""
    Distribution = "dx"
    """Distribution, `E_elc_dx`: embedded generation (cogeneration, run-of-river,
    biogas), with no transmission losses."""

    def get_commodity(self) -> str:
        """
        Electricity commodity of this level.

        Examples
        --------
        >>> GridLevel.Distribution.get_commodity()
        'E_elc_dx'
        """
        return f"E_elc_{self.value}"


class GenerationTechnology(StrEnum):
    """Electricity generation technologies. Configs take the value."""

    Biogas = "biogas"
    """Biogas generation."""
    Biomass = "biomass"
    """Dedicated biomass generation."""
    BiomassCogeneration = "biomass_cg"
    """Biomass heat and power cogeneration."""
    Coal = "coal"
    """Coal generation."""
    CoalCCS = "coal_ccs"
    """Coal generation with 95% carbon capture."""
    DieselCT = "diesel_ct"
    """Diesel combustion turbine."""
    DieselST = "diesel_st"
    """Diesel steam turbine."""
    Geothermal = "geothermal"
    """Geothermal generation."""
    GasolineCT = "gasoline_ct"
    """Gasoline combustion turbine."""
    HydroDaily = "hydro_daily"
    """Hydroelectric generation with a daily reservoir."""
    HydroMonthly = "hydro_monthly"
    """Hydroelectric generation with a monthly (seasonal) reservoir."""
    HydroRunOfRiver = "hydro_run"
    """Run-of-river hydroelectric generation."""
    NaturalGasCC = "ng_cc"
    """Natural gas combined cycle."""
    NaturalGasCCS = "ng_ccs"
    """Natural gas combined cycle with 95% carbon capture."""
    NaturalGasCogeneration = "ng_cg"
    """Natural gas heat and power cogeneration."""
    NaturalGasCT = "ng_ct"
    """Natural gas combustion turbine."""
    NuclearCANDU = "nuclear_candu"
    """CANDU nuclear reactor."""
    NuclearPWR = "nuclear_pwr"
    """Large pressurised water nuclear reactor."""
    NuclearSMR = "nuclear_smr"
    """Small modular nuclear reactor."""
    OilCT = "oil_ct"
    """Oil combustion turbine."""
    OilST = "oil_st"
    """Oil steam turbine."""
    SolarPV = "solar"
    """Utility-scale solar photovoltaic."""
    WindOffshore = "wind_offshore"
    """Offshore wind."""
    WindOnshore = "wind_onshore"
    """Onshore wind."""

    def get_tech_code(self) -> str:
        """
        Base of the technology names, before the `-EXS`/`-NEW` suffix.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCT.get_tech_code()
        'E_NG_CT'
        """
        TECH_CODES = {
            GenerationTechnology.Biogas: "E_BIO_G",
            GenerationTechnology.Biomass: "E_BIO_M",
            GenerationTechnology.BiomassCogeneration: "E_BIO_M_CG",
            GenerationTechnology.Coal: "E_COAL",
            GenerationTechnology.CoalCCS: "E_COAL_CCS",
            GenerationTechnology.DieselCT: "E_DSL_CT",
            GenerationTechnology.DieselST: "E_DSL_ST",
            GenerationTechnology.Geothermal: "E_GEO",
            GenerationTechnology.GasolineCT: "E_GSL_CT",
            GenerationTechnology.HydroDaily: "E_HYD_DLY",
            GenerationTechnology.HydroMonthly: "E_HYD_MLY",
            GenerationTechnology.HydroRunOfRiver: "E_HYD_ROR",
            GenerationTechnology.NaturalGasCC: "E_NG_CC",
            GenerationTechnology.NaturalGasCCS: "E_NG_CCS",
            GenerationTechnology.NaturalGasCogeneration: "E_NG_CG",
            GenerationTechnology.NaturalGasCT: "E_NG_CT",
            GenerationTechnology.NuclearCANDU: "E_NUC_CANDU",
            GenerationTechnology.NuclearPWR: "E_NUC_PWR",
            GenerationTechnology.NuclearSMR: "E_NUC_SMR",
            GenerationTechnology.OilCT: "E_OIL_CT",
            GenerationTechnology.OilST: "E_OIL_ST",
            GenerationTechnology.SolarPV: "E_SOL_PV",
            GenerationTechnology.WindOffshore: "E_WND_OFF",
            GenerationTechnology.WindOnshore: "E_WND_ON",
        }
        return TECH_CODES[self]

    def get_input_fuel(self) -> CANOEFuel | None:
        """
        Fuel the technology burns, supplied by the fuel module, or `None` for a
        free resource (water, wind, sun, heat) taken from `E_ethos`.

        Examples
        --------
        >>> GenerationTechnology.NuclearSMR.get_input_fuel()
        EnrichedUranium
        >>> GenerationTechnology.WindOnshore.get_input_fuel() is None
        True
        """
        INPUT_FUELS: dict[GenerationTechnology, CANOEFuel | None] = {
            GenerationTechnology.Biogas: CANOEFuel.GaseousBioenergy,
            GenerationTechnology.Biomass: CANOEFuel.SolidBioenergy,
            GenerationTechnology.BiomassCogeneration: CANOEFuel.SolidBioenergy,
            GenerationTechnology.Coal: CANOEFuel.Coal,
            GenerationTechnology.CoalCCS: CANOEFuel.Coal,
            GenerationTechnology.DieselCT: CANOEFuel.Diesel,
            GenerationTechnology.DieselST: CANOEFuel.Diesel,
            GenerationTechnology.Geothermal: None,
            GenerationTechnology.GasolineCT: CANOEFuel.Gasoline,
            GenerationTechnology.HydroDaily: None,
            GenerationTechnology.HydroMonthly: None,
            GenerationTechnology.HydroRunOfRiver: None,
            GenerationTechnology.NaturalGasCC: CANOEFuel.NaturalGas,
            GenerationTechnology.NaturalGasCCS: CANOEFuel.NaturalGas,
            GenerationTechnology.NaturalGasCogeneration: CANOEFuel.NaturalGas,
            GenerationTechnology.NaturalGasCT: CANOEFuel.NaturalGas,
            GenerationTechnology.NuclearCANDU: CANOEFuel.NaturalUranium,
            GenerationTechnology.NuclearPWR: CANOEFuel.EnrichedUranium,
            GenerationTechnology.NuclearSMR: CANOEFuel.EnrichedUranium,
            GenerationTechnology.OilCT: CANOEFuel.Oil,
            GenerationTechnology.OilST: CANOEFuel.Oil,
            GenerationTechnology.SolarPV: None,
            GenerationTechnology.WindOffshore: None,
            GenerationTechnology.WindOnshore: None,
        }
        return INPUT_FUELS[self]

    def get_grid_level(self) -> GridLevel:
        """
        Grid level the technology injects into: distribution for embedded
        generation (biogas, cogeneration, run-of-river), transmission otherwise.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCogeneration.get_grid_level()
        <GridLevel.Distribution: 'dx'>
        """
        DISTRIBUTION = (
            GenerationTechnology.Biogas,
            GenerationTechnology.BiomassCogeneration,
            GenerationTechnology.HydroRunOfRiver,
            GenerationTechnology.NaturalGasCogeneration,
        )
        return (
            GridLevel.Distribution if self in DISTRIBUTION else GridLevel.Transmission
        )

    def is_baseload(self) -> bool:
        """
        Whether the technology runs at a constant output within each season (Temoa
        flag `pb`): biogas and nuclear.

        Examples
        --------
        >>> GenerationTechnology.NuclearCANDU.is_baseload()
        True
        """
        return self in (
            GenerationTechnology.Biogas,
            GenerationTechnology.NuclearCANDU,
            GenerationTechnology.NuclearPWR,
            GenerationTechnology.NuclearSMR,
        )

    def is_curtailable(self) -> bool:
        """
        Whether output below the capacity factor can be curtailed (Temoa
        `curtail`): run-of-river, solar and wind.

        Examples
        --------
        >>> GenerationTechnology.SolarPV.is_curtailable()
        True
        """
        return self in (
            GenerationTechnology.HydroRunOfRiver,
            GenerationTechnology.SolarPV,
            GenerationTechnology.WindOffshore,
            GenerationTechnology.WindOnshore,
        )

    def is_resource_binned(self) -> bool:
        """
        Whether new capacity comes as resource bins, each with its own costs,
        capacity limit and profile (`<code>-NEW-<n>`): onshore wind and solar.

        Examples
        --------
        >>> GenerationTechnology.WindOnshore.is_resource_binned()
        True
        """
        return self in (GenerationTechnology.SolarPV, GenerationTechnology.WindOnshore)

    def can_be_new(self) -> bool:
        """
        Whether the model can build new capacity of the technology: it needs NREL
        ATB costs, and, if it burns no fuel, capacity factors (only the resource bins
        have them). Technologies without ATB data would need CODERS investment
        costs, which the previous module never got to work.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCC.can_be_new()
        True
        >>> GenerationTechnology.WindOffshore.can_be_new()  # no capacity factors
        False
        >>> GenerationTechnology.Biogas.can_be_new()  # no ATB data
        False
        """
        if self.get_atb_display_name() is None:
            return False
        return self.get_input_fuel() is not None or self.is_resource_binned()

    def get_atb_first_year(self) -> int | None:
        """
        Earliest year the NREL ATB values of the technology are read at, if later
        than the first ATB year: 2030 for new nuclear, which cannot be built
        sooner.

        Examples
        --------
        >>> GenerationTechnology.NuclearSMR.get_atb_first_year()
        2030
        >>> GenerationTechnology.NaturalGasCC.get_atb_first_year() is None
        True
        """
        if self in (GenerationTechnology.NuclearPWR, GenerationTechnology.NuclearSMR):
            return 2030
        return None

    def is_cogeneration(self) -> bool:
        """
        Whether the technology also produces heat for a host site: its existing
        units must keep their historical electricity output (see
        `generation.parameters.cogeneration_activity`).

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCogeneration.is_cogeneration()
        True
        """
        return self in (
            GenerationTechnology.BiomassCogeneration,
            GenerationTechnology.NaturalGasCogeneration,
        )

    def never_retires(self) -> bool:
        """
        Whether existing units are kept for the whole horizon, whatever their age
        (hydro): they are grouped in a single vintage, the year before the first
        period, with a lifetime of 100 years.

        Examples
        --------
        >>> GenerationTechnology.HydroDaily.never_retires()
        True
        """
        return self in (
            GenerationTechnology.HydroDaily,
            GenerationTechnology.HydroMonthly,
            GenerationTechnology.HydroRunOfRiver,
        )

    def get_description(self) -> str:
        """
        Description in the `technology` table, before the `existing`/`new` suffix.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCT.get_description()
        'natural gas combustion turbine generation'
        """
        DESCRIPTIONS = {
            GenerationTechnology.Biogas: "biogas generation",
            GenerationTechnology.Biomass: "biomass generation",
            GenerationTechnology.BiomassCogeneration: "biomass heat and power "
            + "cogeneration",
            GenerationTechnology.Coal: "coal generation",
            GenerationTechnology.CoalCCS: "coal generation with 95% ccs",
            GenerationTechnology.DieselCT: "diesel combustion turbine generation",
            GenerationTechnology.DieselST: "diesel steam turbine generation",
            GenerationTechnology.Geothermal: "geothermal generation",
            GenerationTechnology.GasolineCT: "gasoline combustion turbine generation",
            GenerationTechnology.HydroDaily: "hydroelectric generation with daily "
            + "reservoir storage",
            GenerationTechnology.HydroMonthly: "hydroelectric generation with monthly "
            + "reservoir storage",
            GenerationTechnology.HydroRunOfRiver: "hydroelectric run-of-river "
            + "generation",
            GenerationTechnology.NaturalGasCC: "natural gas combined cycle generation",
            GenerationTechnology.NaturalGasCCS: "natural gas combined cycle "
            + "generation with 95% ccs",
            GenerationTechnology.NaturalGasCogeneration: "natural gas heat and power "
            + "cogeneration",
            GenerationTechnology.NaturalGasCT: "natural gas combustion turbine "
            + "generation",
            GenerationTechnology.NuclearCANDU: "nuclear candu generation",
            GenerationTechnology.NuclearPWR: "nuclear pressurised water reactor "
            + "generation",
            GenerationTechnology.NuclearSMR: "nuclear small modular reactor generation",
            GenerationTechnology.OilCT: "oil combustion turbine generation",
            GenerationTechnology.OilST: "oil steam turbine generation",
            GenerationTechnology.SolarPV: "utility-scale solar photovoltaic generation",
            GenerationTechnology.WindOffshore: "offshore wind generation",
            GenerationTechnology.WindOnshore: "onshore wind generation",
        }
        return DESCRIPTIONS[self]

    def get_coders_fleet_types(self) -> tuple[str, ...]:
        """
        CODERS `generators` types (`gen_type`, lowercase) whose units are this
        technology's existing capacity; empty if CODERS has none.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCT.get_coders_fleet_types()
        ('ng_sc', 'ng_ct', 'gas_ct')
        """
        FLEET_TYPES: dict[GenerationTechnology, tuple[str, ...]] = {
            GenerationTechnology.Biogas: ("biogas",),
            GenerationTechnology.Biomass: ("biomass", "msw"),
            GenerationTechnology.BiomassCogeneration: ("biomass_cg",),
            GenerationTechnology.Coal: ("coal",),
            GenerationTechnology.CoalCCS: ("coal_ccs",),
            GenerationTechnology.DieselCT: ("diesel_ct",),
            GenerationTechnology.DieselST: ("diesel_st",),
            GenerationTechnology.Geothermal: ("geothermal",),
            GenerationTechnology.GasolineCT: ("gasoline_ct",),
            GenerationTechnology.HydroDaily: ("hydro_daily",),
            GenerationTechnology.HydroMonthly: ("hydro_monthly",),
            GenerationTechnology.HydroRunOfRiver: ("hydro_run",),
            GenerationTechnology.NaturalGasCC: ("ng_cc",),
            GenerationTechnology.NaturalGasCCS: ("ng_ccs",),
            GenerationTechnology.NaturalGasCogeneration: ("ng_cg",),
            GenerationTechnology.NaturalGasCT: ("ng_sc", "ng_ct", "gas_ct"),
            GenerationTechnology.NuclearCANDU: ("nuclear",),
            GenerationTechnology.NuclearPWR: (),
            GenerationTechnology.NuclearSMR: ("nuclear_smr",),
            GenerationTechnology.OilCT: ("oil_ct",),
            GenerationTechnology.OilST: ("oil_st",),
            GenerationTechnology.SolarPV: ("solar_pv", "solar"),
            GenerationTechnology.WindOffshore: ("wind_ofs",),
            GenerationTechnology.WindOnshore: ("wind_ons",),
        }
        return FLEET_TYPES[self]

    def get_coders_generic_type(self) -> str:
        """
        CODERS `generation_generic` type (`gen_type`, lowercase) the technology takes
        its lifetime from, and its efficiency and costs when it has no NREL ATB
        equivalent.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCT.get_coders_generic_type()
        'ng_sc'
        """
        GENERIC_TYPES = {
            GenerationTechnology.Biogas: "biogas",
            GenerationTechnology.Biomass: "biomass",
            GenerationTechnology.BiomassCogeneration: "biomass_cg",
            GenerationTechnology.Coal: "coal",
            GenerationTechnology.CoalCCS: "coal_ccs",
            GenerationTechnology.DieselCT: "diesel_ct",
            GenerationTechnology.DieselST: "diesel_st",
            GenerationTechnology.Geothermal: "geothermal",
            GenerationTechnology.GasolineCT: "gasoline_ct",
            GenerationTechnology.HydroDaily: "hydro_daily",
            GenerationTechnology.HydroMonthly: "hydro_monthly",
            GenerationTechnology.HydroRunOfRiver: "hydro_run",
            GenerationTechnology.NaturalGasCC: "ng_cc",
            GenerationTechnology.NaturalGasCCS: "ng_ccs",
            GenerationTechnology.NaturalGasCogeneration: "ng_cg",
            GenerationTechnology.NaturalGasCT: "ng_sc",
            GenerationTechnology.NuclearCANDU: "nuclear",
            GenerationTechnology.NuclearPWR: "nuclear",
            GenerationTechnology.NuclearSMR: "nuclear_smr",
            GenerationTechnology.OilCT: "oil_ct",
            GenerationTechnology.OilST: "oil_st",
            GenerationTechnology.SolarPV: "solar_pv",
            GenerationTechnology.WindOffshore: "wind_offshore",
            GenerationTechnology.WindOnshore: "wind_onshore",
        }
        return GENERIC_TYPES[self]

    def get_atb_display_name(self) -> str | None:
        """
        NREL ATB technology (`display_name`) the technology takes its efficiency
        (heat rate) and costs from, or `None` to take them from CODERS.

        Examples
        --------
        >>> GenerationTechnology.NaturalGasCT.get_atb_display_name()
        'NG Combustion Turbine (F-Frame)'
        >>> GenerationTechnology.NuclearCANDU.get_atb_display_name() is None
        True
        """
        DISPLAY_NAMES: dict[GenerationTechnology, str | None] = {
            GenerationTechnology.Biogas: None,
            GenerationTechnology.Biomass: "Biopower - Dedicated",
            GenerationTechnology.BiomassCogeneration: "Biopower - Dedicated",
            GenerationTechnology.Coal: "Coal-new",
            GenerationTechnology.CoalCCS: "Coal-95%-CCS",
            GenerationTechnology.DieselCT: None,
            GenerationTechnology.DieselST: None,
            GenerationTechnology.Geothermal: "Geothermal - Hydro / Flash",
            GenerationTechnology.GasolineCT: None,
            GenerationTechnology.HydroDaily: None,
            GenerationTechnology.HydroMonthly: None,
            GenerationTechnology.HydroRunOfRiver: None,
            GenerationTechnology.NaturalGasCC: "NG 2-on-1 Combined Cycle (H-Frame)",
            GenerationTechnology.NaturalGasCCS: "NG 2-on-1 Combined Cycle (H-Frame) "
            + "95% CCS",
            GenerationTechnology.NaturalGasCogeneration: None,
            GenerationTechnology.NaturalGasCT: "NG Combustion Turbine (F-Frame)",
            GenerationTechnology.NuclearCANDU: None,
            GenerationTechnology.NuclearPWR: "Nuclear - Large",
            GenerationTechnology.NuclearSMR: "Nuclear - Small",
            GenerationTechnology.OilCT: None,
            GenerationTechnology.OilST: None,
            GenerationTechnology.SolarPV: "Utility PV - Class 3",
            GenerationTechnology.WindOffshore: "Offshore Wind - Class 3",
            GenerationTechnology.WindOnshore: "Land-Based Wind - Class 7 - Technology 1",
        }
        return DISPLAY_NAMES[self]


class StorageTechnology(StrEnum):
    """Electricity storage technologies, on the transmission level. Configs take
    the value."""

    Battery1h = "battery_1h"
    """Utility-scale lithium-ion battery, 1 hour."""
    Battery2h = "battery_2h"
    """Utility-scale lithium-ion battery, 2 hours."""
    Battery3h = "battery_3h"
    """Utility-scale lithium-ion battery, 3 hours."""
    Battery4h = "battery_4h"
    """Utility-scale lithium-ion battery, 4 hours."""
    Battery5h = "battery_5h"
    """Utility-scale lithium-ion battery, 5 hours."""
    PumpedHydro4h = "pump_4h"
    """Pumped hydroelectric storage, 4 hours."""
    PumpedHydro10h = "pump_10h"
    """Pumped hydroelectric storage, 10 hours."""

    def get_tech_code(self) -> str:
        """
        Base of the technology names, before the `-EXS`/`-NEW` suffix.

        Examples
        --------
        >>> StorageTechnology.PumpedHydro4h.get_tech_code()
        'E_PUMP_4H'
        """
        TECH_CODES = {
            StorageTechnology.Battery1h: "E_BAT_1H",
            StorageTechnology.Battery2h: "E_BAT_2H",
            StorageTechnology.Battery3h: "E_BAT_3H",
            StorageTechnology.Battery4h: "E_BAT_4H",
            StorageTechnology.Battery5h: "E_BAT_5H",
            StorageTechnology.PumpedHydro4h: "E_PUMP_4H",
            StorageTechnology.PumpedHydro10h: "E_PUMP_10H",
        }
        return TECH_CODES[self]

    def get_duration_hours(self) -> int:
        """
        Hours of output at full power from full storage.

        Examples
        --------
        >>> StorageTechnology.Battery4h.get_duration_hours()
        4
        """
        DURATIONS = {
            StorageTechnology.Battery1h: 1,
            StorageTechnology.Battery2h: 2,
            StorageTechnology.Battery3h: 3,
            StorageTechnology.Battery4h: 4,
            StorageTechnology.Battery5h: 5,
            StorageTechnology.PumpedHydro4h: 4,
            StorageTechnology.PumpedHydro10h: 10,
        }
        return DURATIONS[self]


class CCSRetrofit(StrEnum):
    """Carbon capture retrofits of fossil generators. Configs take the value."""

    Coal90 = "coal_ccs_retrofit_90"
    """90% capture retrofit of coal generation."""
    Coal95 = "coal_ccs_retrofit_95"
    """95% capture retrofit of coal generation."""
    NaturalGasCC90 = "ng_ccs_retrofit_90"
    """90% capture retrofit of natural gas combined cycle."""
    NaturalGasCC95 = "ng_ccs_retrofit_95"
    """95% capture retrofit of natural gas combined cycle."""

    def get_tech_code(self) -> str:
        """
        Examples
        --------
        >>> CCSRetrofit.NaturalGasCC90.get_tech_code()
        'E_NG_CCS_RFIT_90'
        """
        TECH_CODES = {
            CCSRetrofit.Coal90: "E_COAL_CCS_RFIT_90",
            CCSRetrofit.Coal95: "E_COAL_CCS_RFIT_95",
            CCSRetrofit.NaturalGasCC90: "E_NG_CCS_RFIT_90",
            CCSRetrofit.NaturalGasCC95: "E_NG_CCS_RFIT_95",
        }
        return TECH_CODES[self]

    def get_generator(self) -> GenerationTechnology:
        """
        Generator the retrofit applies to.

        Examples
        --------
        >>> CCSRetrofit.Coal95.get_generator()
        <GenerationTechnology.Coal: 'coal'>
        """
        GENERATORS = {
            CCSRetrofit.Coal90: GenerationTechnology.Coal,
            CCSRetrofit.Coal95: GenerationTechnology.Coal,
            CCSRetrofit.NaturalGasCC90: GenerationTechnology.NaturalGasCC,
            CCSRetrofit.NaturalGasCC95: GenerationTechnology.NaturalGasCC,
        }
        return GENERATORS[self]

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

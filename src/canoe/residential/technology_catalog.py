"""
Catalog of the residential technologies: the new technologies users can choose and
the existing technologies of the NRCan stock.

Users choose new technologies by their readable name (`NewTechnology`, e.g.
"air-source heat pump") in the `new_technologies` list of each end use table. Each
technology's specification (`spec()`) holds the rest: its name in the model, fuel,
the end uses it serves, its equipment in the AEO residential technology menu, its
fixed cost, and the existing technology whose capacity factor it takes. Existing
technologies (`ExistingTechnology`) are always modelled where they have stock; their
specification says which NRCan rows they stand for.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from canoe.common import CANOEFuel

from .end_uses import ResidentialEndUse


@dataclass(frozen=True)
class NewTechnologySpec:
    """
    Parameters
    ----------
    name : str
        Technology name in the model (as the previous module, e.g.
        "R_SPHC_AIR_HP-TYP-NEW").
    fuel : CANOEFuel or None
        Input fuel; None for the solar water heater, which takes the free source
        commodity `R_ethos` (see `RESIDENTIAL_MODULE_BUGS.md`).
    end_uses : tuple[ResidentialEndUse, ...]
        End uses it can serve (heat pumps: space heating and space cooling).
    aeo_class : str or None
        AEO equipment class (sheet RSCLASS): lifetime, base efficiency and
        efficiency metric. None for lamps.
    aeo_equipment : str or None
        AEO equipment (sheet RSMEQP): efficiency and investment cost. None for lamps.
    fixed_cost : float or None
        Fixed operation and maintenance cost, USD (2022) per unit and year (EIA,
        2023, Updated Buildings Sector Appliance and Equipment Costs and
        Efficiency). None for lamps (AEO lighting data).
    equivalents : dict[ResidentialEndUse, ExistingTechnology]
        Existing technology whose annual capacity factor it takes, for each end use
        it serves (appliances: also its efficiency, scaled). Empty for lamps.
    lamp : str or None
        Code of the lamp in the AEO lighting data (e.g. "led-hef"); lamps only.
    """

    name: str
    fuel: CANOEFuel | None
    end_uses: tuple[ResidentialEndUse, ...]
    aeo_class: str | None = None
    aeo_equipment: str | None = None
    fixed_cost: float | None = None
    equivalents: dict[ResidentialEndUse, "ExistingTechnology"] = field(
        default_factory=dict
    )
    lamp: str | None = None


class NewTechnology(StrEnum):
    """
    Technologies that can be built to serve the residential end uses
    (`new_technologies`). Values are the names used in the TOML. A name is the
    typical efficiency equipment of the AEO residential technology menu; "high
    efficiency" marks its high efficiency variant, where AEO has one.
    """

    # Space heating
    ElectricRadiator = "electric radiator"
    NaturalGasFurnace = "natural gas furnace"
    NaturalGasFurnaceHighEfficiency = "natural gas furnace high efficiency"
    NaturalGasBoiler = "natural gas boiler"
    NaturalGasBoilerHighEfficiency = "natural gas boiler high efficiency"
    OilFurnace = "oil furnace"
    OilFurnaceHighEfficiency = "oil furnace high efficiency"
    OilBoiler = "oil boiler"
    OilBoilerHighEfficiency = "oil boiler high efficiency"
    LPGFurnace = "lpg furnace"
    LPGFurnaceHighEfficiency = "lpg furnace high efficiency"
    WoodStove = "wood stove"
    WoodStoveHighEfficiency = "wood stove high efficiency"
    # Space heating and cooling
    AirSourceHeatPump = "air-source heat pump"
    AirSourceHeatPumpHighEfficiency = "air-source heat pump high efficiency"
    GeoExchangeHeatPump = "geo-exchange heat pump"
    GeoExchangeHeatPumpHighEfficiency = "geo-exchange heat pump high efficiency"
    NaturalGasHeatPump = "natural gas heat pump"
    # Space cooling
    CentralAirConditioner = "central air conditioner"
    CentralAirConditionerHighEfficiency = "central air conditioner high efficiency"
    RoomAirConditioner = "room air conditioner"
    RoomAirConditionerHighEfficiency = "room air conditioner high efficiency"
    # Water heating
    ElectricWaterHeater = "electric water heater"
    ElectricWaterHeaterHighEfficiency = "electric water heater high efficiency"
    HeatPumpWaterHeater = "heat pump water heater"
    HeatPumpWaterHeaterHighEfficiency = "heat pump water heater high efficiency"
    NaturalGasWaterHeater = "natural gas water heater"
    NaturalGasWaterHeaterHighEfficiency = "natural gas water heater high efficiency"
    OilWaterHeater = "oil water heater"
    OilWaterHeaterHighEfficiency = "oil water heater high efficiency"
    LPGWaterHeater = "lpg water heater"
    LPGWaterHeaterHighEfficiency = "lpg water heater high efficiency"
    SolarWaterHeater = "solar water heater"
    # Lighting
    IncandescentBulb = "incandescent bulb"
    HalogenBulb = "halogen bulb"
    CompactFluorescentBulb = "compact fluorescent bulb"
    CompactFluorescentBulbHighEfficiency = "compact fluorescent bulb high efficiency"
    LEDBulb = "led bulb"
    LEDBulbHighEfficiency = "led bulb high efficiency"
    LinearFluorescentLamp = "linear fluorescent lamp"
    # Appliances
    Refrigerator = "refrigerator"
    RefrigeratorHighEfficiency = "refrigerator high efficiency"
    Freezer = "freezer"
    FreezerHighEfficiency = "freezer high efficiency"
    DishWasher = "dish washer"
    DishWasherHighEfficiency = "dish washer high efficiency"
    ClothesWasher = "clothes washer"
    ClothesWasherHighEfficiency = "clothes washer high efficiency"
    ElectricClothesDryer = "electric clothes dryer"
    ElectricClothesDryerHighEfficiency = "electric clothes dryer high efficiency"
    NaturalGasClothesDryer = "natural gas clothes dryer"
    NaturalGasClothesDryerHighEfficiency = "natural gas clothes dryer high efficiency"
    ElectricCookingRange = "electric cooking range"
    NaturalGasCookingRange = "natural gas cooking range"
    NaturalGasCookingRangeHighEfficiency = "natural gas cooking range high efficiency"
    LPGCookingRange = "lpg cooking range"
    LPGCookingRangeHighEfficiency = "lpg cooking range high efficiency"

    def end_uses(self) -> tuple[ResidentialEndUse, ...]:
        """
        End uses the technology can serve.

        Examples
        --------
        >>> NewTechnology.AirSourceHeatPump.end_uses()
        (SpaceHeating, SpaceCooling)
        """
        return self.spec().end_uses

    def spec(self) -> NewTechnologySpec:
        """
        Examples
        --------
        >>> NewTechnology.NaturalGasFurnaceHighEfficiency.spec().aeo_equipment
        'NG_FA4'
        """
        T = NewTechnology
        E = ResidentialEndUse
        F = CANOEFuel
        X = ExistingTechnology
        SPECS: dict[NewTechnology, NewTechnologySpec] = {
            T.ElectricRadiator: NewTechnologySpec(
                name="R_SPH_ELEC_RAD-NEW",
                fuel=F.Electricity,
                end_uses=(E.SpaceHeating,),
                aeo_class="ELEC_RAD",
                aeo_equipment="ELEC_RAD2",
                fixed_cost=0.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingElectric},
            ),
            T.NaturalGasFurnace: NewTechnologySpec(
                name="R_SPH_NG_FRN-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="NG_FA",
                aeo_equipment="NG_FA2",
                fixed_cost=130.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingNaturalGas},
            ),
            T.NaturalGasFurnaceHighEfficiency: NewTechnologySpec(
                name="R_SPH_NG_FRN-HEF-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="NG_FA",
                aeo_equipment="NG_FA4",
                fixed_cost=130.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingNaturalGas},
            ),
            T.NaturalGasBoiler: NewTechnologySpec(
                name="R_SPH_NG_BLR-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="NG_RAD",
                aeo_equipment="NG_RAD2",
                fixed_cost=160.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingNaturalGas},
            ),
            T.NaturalGasBoilerHighEfficiency: NewTechnologySpec(
                name="R_SPH_NG_BLR-HEF-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="NG_RAD",
                aeo_equipment="NG_RAD4",
                fixed_cost=160.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingNaturalGas},
            ),
            T.OilFurnace: NewTechnologySpec(
                name="R_SPH_OIL_FRN-TYP-NEW",
                fuel=F.Oil,
                end_uses=(E.SpaceHeating,),
                aeo_class="DIST_FA",
                aeo_equipment="DIST_FA2",
                fixed_cost=80.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingOil},
            ),
            T.OilFurnaceHighEfficiency: NewTechnologySpec(
                name="R_SPH_OIL_FRN-HEF-NEW",
                fuel=F.Oil,
                end_uses=(E.SpaceHeating,),
                aeo_class="DIST_FA",
                aeo_equipment="DIST_FA4",
                fixed_cost=80.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingOil},
            ),
            T.OilBoiler: NewTechnologySpec(
                name="R_SPH_OIL_BLR-TYP-NEW",
                fuel=F.Oil,
                end_uses=(E.SpaceHeating,),
                aeo_class="DIST_RAD",
                # The previous module's DIST_RAD2 is not in this AEO edition: the
                # base oil boiler stands in (see RESIDENTIAL_MODULE_BUGS.md)
                aeo_equipment="DIST_RAD1",
                fixed_cost=170.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingOil},
            ),
            T.OilBoilerHighEfficiency: NewTechnologySpec(
                name="R_SPH_OIL_BLR-HEF-NEW",
                fuel=F.Oil,
                end_uses=(E.SpaceHeating,),
                aeo_class="DIST_RAD",
                aeo_equipment="DIST_RAD4",
                fixed_cost=170.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingOil},
            ),
            T.LPGFurnace: NewTechnologySpec(
                name="R_SPH_LPG-TYP-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="LPG_FA",
                aeo_equipment="LPG_FA2",
                fixed_cost=130.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingLPG},
            ),
            T.LPGFurnaceHighEfficiency: NewTechnologySpec(
                name="R_SPH_LPG-HEF-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.SpaceHeating,),
                aeo_class="LPG_FA",
                aeo_equipment="LPG_FA4",
                fixed_cost=130.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingLPG},
            ),
            T.WoodStove: NewTechnologySpec(
                name="R_SPH_WOOD-TYP-NEW",
                fuel=F.Wood,
                end_uses=(E.SpaceHeating,),
                aeo_class="WOOD_HT",
                aeo_equipment="WOOD_HT2",
                fixed_cost=190.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingWood},
            ),
            T.WoodStoveHighEfficiency: NewTechnologySpec(
                name="R_SPH_WOOD-HEF-NEW",
                fuel=F.Wood,
                end_uses=(E.SpaceHeating,),
                aeo_class="WOOD_HT",
                aeo_equipment="WOOD_HT4",
                fixed_cost=190.0,
                equivalents={E.SpaceHeating: X.SpaceHeatingWood},
            ),
            T.AirSourceHeatPump: NewTechnologySpec(
                name="R_SPHC_AIR_HP-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(
                    E.SpaceHeating,
                    E.SpaceCooling,
                ),
                aeo_class="ELEC_HP",
                aeo_equipment="ELEC_HP2",
                fixed_cost=85.0,
                equivalents={
                    E.SpaceHeating: X.SpaceHeatingHeatPump,
                    E.SpaceCooling: X.CentralAirConditioner,
                },
            ),
            T.AirSourceHeatPumpHighEfficiency: NewTechnologySpec(
                name="R_SPHC_AIR_HP-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(
                    E.SpaceHeating,
                    E.SpaceCooling,
                ),
                aeo_class="ELEC_HP",
                aeo_equipment="ELEC_HP4",
                fixed_cost=85.0,
                equivalents={
                    E.SpaceHeating: X.SpaceHeatingHeatPump,
                    E.SpaceCooling: X.CentralAirConditioner,
                },
            ),
            T.GeoExchangeHeatPump: NewTechnologySpec(
                name="R_SPHC_GEO_HP-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(
                    E.SpaceHeating,
                    E.SpaceCooling,
                ),
                aeo_class="GEO_HP",
                aeo_equipment="GEO_HP2",
                fixed_cost=90.0,
                equivalents={
                    E.SpaceHeating: X.SpaceHeatingHeatPump,
                    E.SpaceCooling: X.CentralAirConditioner,
                },
            ),
            T.GeoExchangeHeatPumpHighEfficiency: NewTechnologySpec(
                name="R_SPHC_GEO_HP-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(
                    E.SpaceHeating,
                    E.SpaceCooling,
                ),
                aeo_class="GEO_HP",
                aeo_equipment="GEO_HP4",
                fixed_cost=90.0,
                equivalents={
                    E.SpaceHeating: X.SpaceHeatingHeatPump,
                    E.SpaceCooling: X.CentralAirConditioner,
                },
            ),
            T.NaturalGasHeatPump: NewTechnologySpec(
                name="R_SPHC_NG_HP-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(
                    E.SpaceHeating,
                    E.SpaceCooling,
                ),
                aeo_class="NG_HP",
                aeo_equipment="NG_HP2",
                fixed_cost=200.0,
                equivalents={
                    E.SpaceHeating: X.SpaceHeatingHeatPump,
                    E.SpaceCooling: X.CentralAirConditioner,
                },
            ),
            T.CentralAirConditioner: NewTechnologySpec(
                name="R_SPC_CENT_AC-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.SpaceCooling,),
                aeo_class="CENT_AIR",
                aeo_equipment="CENT_AIR2",
                fixed_cost=85.0,
                equivalents={E.SpaceCooling: X.CentralAirConditioner},
            ),
            T.CentralAirConditionerHighEfficiency: NewTechnologySpec(
                name="R_SPC_CENT_AC-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.SpaceCooling,),
                aeo_class="CENT_AIR",
                aeo_equipment="CENT_AIR4",
                fixed_cost=85.0,
                equivalents={E.SpaceCooling: X.CentralAirConditioner},
            ),
            T.RoomAirConditioner: NewTechnologySpec(
                name="R_SPC_ROOM_AC-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.SpaceCooling,),
                aeo_class="ROOM_AIR",
                aeo_equipment="ROOM_AIR1",
                fixed_cost=0.0,
                equivalents={E.SpaceCooling: X.RoomAirConditioner},
            ),
            T.RoomAirConditionerHighEfficiency: NewTechnologySpec(
                name="R_SPC_ROOM_AC-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.SpaceCooling,),
                aeo_class="ROOM_AIR",
                aeo_equipment="ROOM_AIR4",
                fixed_cost=0.0,
                equivalents={E.SpaceCooling: X.RoomAirConditioner},
            ),
            T.ElectricWaterHeater: NewTechnologySpec(
                name="R_WAH_ELEC-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.WaterHeating,),
                aeo_class="ELEC_WH",
                aeo_equipment="ELEC_WH1",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.ElectricWaterHeater},
            ),
            T.ElectricWaterHeaterHighEfficiency: NewTechnologySpec(
                name="R_WAH_ELEC-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.WaterHeating,),
                aeo_class="ELEC_WH",
                aeo_equipment="ELEC_WH4",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.ElectricWaterHeater},
            ),
            T.HeatPumpWaterHeater: NewTechnologySpec(
                name="R_WAH_HP-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.WaterHeating,),
                aeo_class="ELEC_WH",
                aeo_equipment="ELEC_WH6",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.ElectricWaterHeater},
            ),
            T.HeatPumpWaterHeaterHighEfficiency: NewTechnologySpec(
                name="R_WAH_HP-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.WaterHeating,),
                aeo_class="ELEC_WH",
                aeo_equipment="ELEC_WH8",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.ElectricWaterHeater},
            ),
            T.NaturalGasWaterHeater: NewTechnologySpec(
                name="R_WAH_NG-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.WaterHeating,),
                aeo_class="NG_WH",
                aeo_equipment="NG_WH1",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.NaturalGasWaterHeater},
            ),
            T.NaturalGasWaterHeaterHighEfficiency: NewTechnologySpec(
                name="R_WAH_NG-HEF-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.WaterHeating,),
                aeo_class="NG_WH",
                aeo_equipment="NG_WH4",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.NaturalGasWaterHeater},
            ),
            T.OilWaterHeater: NewTechnologySpec(
                name="R_WAH_OIL-TYP-NEW",
                fuel=F.Oil,
                end_uses=(E.WaterHeating,),
                aeo_class="DIST_WH",
                aeo_equipment="DIST_WH2",
                fixed_cost=210.0,
                equivalents={E.WaterHeating: X.OilWaterHeater},
            ),
            T.OilWaterHeaterHighEfficiency: NewTechnologySpec(
                name="R_WAH_OIL-HEF-NEW",
                fuel=F.Oil,
                end_uses=(E.WaterHeating,),
                aeo_class="DIST_WH",
                aeo_equipment="DIST_WH4",
                fixed_cost=210.0,
                equivalents={E.WaterHeating: X.OilWaterHeater},
            ),
            T.LPGWaterHeater: NewTechnologySpec(
                name="R_WAH_LPG-TYP-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.WaterHeating,),
                aeo_class="LPG_WH",
                # The previous module's LPG_WH2 is not in this AEO edition: LPG_WH1
                # stands in, like NG_WH1 for the typical natural gas water heater
                # (see RESIDENTIAL_MODULE_BUGS.md)
                aeo_equipment="LPG_WH1",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.LPGWaterHeater},
            ),
            T.LPGWaterHeaterHighEfficiency: NewTechnologySpec(
                name="R_WAH_LPG-HEF-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.WaterHeating,),
                aeo_class="LPG_WH",
                aeo_equipment="LPG_WH4",
                fixed_cost=20.0,
                equivalents={E.WaterHeating: X.LPGWaterHeater},
            ),
            T.SolarWaterHeater: NewTechnologySpec(
                name="R_WAH_SOLAR-TYP-NEW",
                fuel=None,
                end_uses=(E.WaterHeating,),
                aeo_class="SOLAR_WH",
                aeo_equipment="SOLAR_WH2",
                fixed_cost=80.0,
                equivalents={E.WaterHeating: X.ElectricWaterHeater},
            ),
            T.Refrigerator: NewTechnologySpec(
                name="R_APP_REFR-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.Refrigerators,),
                aeo_class="REFR",
                aeo_equipment="REFR_TF2",
                fixed_cost=20.0,
                equivalents={E.Refrigerators: X.Refrigerator},
            ),
            T.RefrigeratorHighEfficiency: NewTechnologySpec(
                name="R_APP_REFR-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.Refrigerators,),
                aeo_class="REFR",
                aeo_equipment="REFR_TF4",
                fixed_cost=20.0,
                equivalents={E.Refrigerators: X.Refrigerator},
            ),
            T.Freezer: NewTechnologySpec(
                name="R_APP_FREZ-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.Freezers,),
                aeo_class="FREZ",
                aeo_equipment="FREZ_C1",
                fixed_cost=10.0,
                equivalents={E.Freezers: X.Freezer},
            ),
            T.FreezerHighEfficiency: NewTechnologySpec(
                name="R_APP_FREZ-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.Freezers,),
                aeo_class="FREZ",
                aeo_equipment="FREZ_C4",
                fixed_cost=10.0,
                equivalents={E.Freezers: X.Freezer},
            ),
            T.DishWasher: NewTechnologySpec(
                name="R_APP_DS_WASH-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.DishWashers,),
                aeo_class="DS_WASH",
                aeo_equipment="DS_WASH3",
                fixed_cost=0.0,
                equivalents={E.DishWashers: X.DishWasher},
            ),
            T.DishWasherHighEfficiency: NewTechnologySpec(
                name="R_APP_DS_WASH-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.DishWashers,),
                aeo_class="DS_WASH",
                aeo_equipment="DS_WASH4",
                fixed_cost=0.0,
                equivalents={E.DishWashers: X.DishWasher},
            ),
            T.ClothesWasher: NewTechnologySpec(
                name="R_APP_CL_WASH-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.ClothesWashers,),
                aeo_class="CL_WASH",
                aeo_equipment="CL_WASH_T1",
                fixed_cost=15.0,
                equivalents={E.ClothesWashers: X.ClothesWasher},
            ),
            T.ClothesWasherHighEfficiency: NewTechnologySpec(
                name="R_APP_CL_WASH-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.ClothesWashers,),
                aeo_class="CL_WASH",
                aeo_equipment="CL_WASH_T4",
                fixed_cost=15.0,
                equivalents={E.ClothesWashers: X.ClothesWasher},
            ),
            T.ElectricClothesDryer: NewTechnologySpec(
                name="R_APP_DRY_ELEC-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.ClothesDryers,),
                aeo_class="ELEC_DRY",
                aeo_equipment="ELEC_DRY1",
                fixed_cost=0.0,
                equivalents={E.ClothesDryers: X.ElectricClothesDryer},
            ),
            T.ElectricClothesDryerHighEfficiency: NewTechnologySpec(
                name="R_APP_DRY_ELEC-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.ClothesDryers,),
                aeo_class="ELEC_DRY",
                aeo_equipment="ELEC_DRY4",
                fixed_cost=0.0,
                equivalents={E.ClothesDryers: X.ElectricClothesDryer},
            ),
            T.NaturalGasClothesDryer: NewTechnologySpec(
                name="R_APP_DRY_NG-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.ClothesDryers,),
                aeo_class="NG_DRY",
                aeo_equipment="NG_DRY1",
                fixed_cost=0.0,
                equivalents={E.ClothesDryers: X.NaturalGasClothesDryer},
            ),
            T.NaturalGasClothesDryerHighEfficiency: NewTechnologySpec(
                name="R_APP_DRY_NG-HEF-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.ClothesDryers,),
                aeo_class="NG_DRY",
                aeo_equipment="NG_DRY4",
                fixed_cost=0.0,
                equivalents={E.ClothesDryers: X.NaturalGasClothesDryer},
            ),
            T.ElectricCookingRange: NewTechnologySpec(
                name="R_APP_COOK_ELEC-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.CookingRanges,),
                aeo_class="ELEC_STV",
                aeo_equipment="ELEC_STV2",
                fixed_cost=0.0,
                equivalents={E.CookingRanges: X.ElectricCookingRange},
            ),
            T.NaturalGasCookingRange: NewTechnologySpec(
                name="R_APP_COOK_NG-TYP-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.CookingRanges,),
                aeo_class="NG_STV",
                aeo_equipment="NG_STV2",
                fixed_cost=0.0,
                equivalents={E.CookingRanges: X.NaturalGasCookingRange},
            ),
            T.NaturalGasCookingRangeHighEfficiency: NewTechnologySpec(
                name="R_APP_COOK_NG-HEF-NEW",
                fuel=F.NaturalGas,
                end_uses=(E.CookingRanges,),
                aeo_class="NG_STV",
                aeo_equipment="NG_STV4",
                fixed_cost=0.0,
                equivalents={E.CookingRanges: X.NaturalGasCookingRange},
            ),
            T.LPGCookingRange: NewTechnologySpec(
                name="R_APP_COOK_LPG-TYP-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.CookingRanges,),
                aeo_class="LPG_STV",
                aeo_equipment="LPG_STV2",
                fixed_cost=0.0,
                equivalents={E.CookingRanges: X.NaturalGasCookingRange},
            ),
            T.LPGCookingRangeHighEfficiency: NewTechnologySpec(
                name="R_APP_COOK_LPG-HEF-NEW",
                fuel=F.LiquifiedPretroleumGas,
                end_uses=(E.CookingRanges,),
                aeo_class="LPG_STV",
                aeo_equipment="LPG_STV4",
                fixed_cost=0.0,
                equivalents={E.CookingRanges: X.NaturalGasCookingRange},
            ),
            T.IncandescentBulb: NewTechnologySpec(
                name="R_LGT_INC-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="inc",
            ),
            T.HalogenBulb: NewTechnologySpec(
                name="R_LGT_HAL-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="hal",
            ),
            T.CompactFluorescentBulb: NewTechnologySpec(
                name="R_LGT_CFL-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="cfl",
            ),
            T.CompactFluorescentBulbHighEfficiency: NewTechnologySpec(
                name="R_LGT_CFL-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="cfl-hef",
            ),
            T.LEDBulb: NewTechnologySpec(
                name="R_LGT_LED-TYP-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="led",
            ),
            T.LEDBulbHighEfficiency: NewTechnologySpec(
                name="R_LGT_LED-HEF-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="led-hef",
            ),
            T.LinearFluorescentLamp: NewTechnologySpec(
                name="R_LGT_T12-NEW",
                fuel=F.Electricity,
                end_uses=(E.Lighting,),
                lamp="t12",
            ),
        }
        return SPECS[self]


@dataclass(frozen=True)
class ExistingTechnologySpec:
    """
    Parameters
    ----------
    description : str
        Short description (e.g. "dual wood-electric").
    end_use : ResidentialEndUse
        End use it serves.
    fuels : tuple[CANOEFuel, ...]
        Input fuels (two for the dual heating systems).
    nrcan_rows : tuple[str, ...]
        NRCan CEUD rows whose stock and energy use it stands for (summed), as
        returned by the loaders (e.g. the three oil efficiency classes). Empty for
        lamps.
    new_equivalent : NewTechnology or None
        New technology whose AEO equipment class (lifetime) and fixed cost it takes,
        the typical efficiency variant of its class. None for other appliances.
    lamp : str or None
        Code of the lamp in the lighting data (e.g. "cfl"); lamps only.
    """

    description: str
    end_use: ResidentialEndUse
    fuels: tuple[CANOEFuel, ...]
    nrcan_rows: tuple[str, ...] = ()
    new_equivalent: NewTechnology | None = None
    lamp: str | None = None


class ExistingTechnology(StrEnum):
    """
    Technologies of the existing NRCan stock, one per system type (values are their
    names in the model, as the previous module). Each is modelled in the provinces
    where it has stock.
    """

    # Space heating
    SpaceHeatingOil = "R_SPH_OIL-EXS"
    SpaceHeatingNaturalGas = "R_SPH_NG-EXS"
    SpaceHeatingElectric = "R_SPH_ELEC-EXS"
    SpaceHeatingHeatPump = "R_SPH_HP-EXS"
    SpaceHeatingLPG = "R_SPH_OTH-EXS"
    SpaceHeatingWood = "R_SPH_WOOD-EXS"
    SpaceHeatingWoodElectric = "R_SPH_WOOD-ELC-EXS"
    SpaceHeatingWoodOil = "R_SPH_WOOD-OIL-EXS"
    SpaceHeatingNaturalGasElectric = "R_SPH_NG-ELC-EXS"
    SpaceHeatingOilElectric = "R_SPH_OIL-ELC-EXS"
    # Space cooling
    RoomAirConditioner = "R_SPC_ROOM_AC-EXS"
    CentralAirConditioner = "R_SPC_CENT_AC-EXS"
    # Water heating
    ElectricWaterHeater = "R_WAH_ELC-EXS"
    NaturalGasWaterHeater = "R_WAH_NG-EXS"
    OilWaterHeater = "R_WAH_OIL-EXS"
    LPGWaterHeater = "R_WAH_LPG-EXS"
    WoodWaterHeater = "R_WAH_WOOD-EXS"
    # Lighting
    IncandescentBulb = "R_LGT_INC-EXS"
    HalogenBulb = "R_LGT_HAL-EXS"
    CompactFluorescentBulb = "R_LGT_CFL-EXS"
    LEDBulb = "R_LGT_LED-EXS"
    LinearFluorescentLamp = "R_LGT_T12-EXS"
    # Appliances
    Refrigerator = "R_APP_REFR-EXS"
    Freezer = "R_APP_FREZ-EXS"
    DishWasher = "R_APP_DS_WASH-EXS"
    ClothesWasher = "R_APP_CL_WASH-EXS"
    ElectricClothesDryer = "R_APP_DRY_ELEC-EXS"
    NaturalGasClothesDryer = "R_APP_DRY_NG-EXS"
    ElectricCookingRange = "R_APP_COOK_ELEC-EXS"
    NaturalGasCookingRange = "R_APP_COOK_NG-EXS"
    OtherAppliances = "R_APP_OTH"
    """Other electrical appliances and devices: no stock, unlimited capacity."""

    def spec(self) -> ExistingTechnologySpec:
        """
        Examples
        --------
        >>> ExistingTechnology.SpaceHeatingWoodOil.spec().fuels
        (Wood, Oil)
        """
        X = ExistingTechnology
        T = NewTechnology
        E = ResidentialEndUse
        F = CANOEFuel
        SPECS: dict[ExistingTechnology, ExistingTechnologySpec] = {
            X.SpaceHeatingOil: ExistingTechnologySpec(
                description="oil",
                end_use=E.SpaceHeating,
                fuels=(F.Oil,),
                nrcan_rows=(
                    "heating oil – normal efficiency",
                    "heating oil – medium efficiency",
                    "heating oil – high efficiency",
                ),
                new_equivalent=T.OilFurnace,
            ),
            X.SpaceHeatingNaturalGas: ExistingTechnologySpec(
                description="natural gas",
                end_use=E.SpaceHeating,
                fuels=(F.NaturalGas,),
                nrcan_rows=(
                    "natural gas – normal efficiency",
                    "natural gas – medium efficiency",
                    "natural gas – high efficiency",
                ),
                new_equivalent=T.NaturalGasFurnace,
            ),
            X.SpaceHeatingElectric: ExistingTechnologySpec(
                description="electric",
                end_use=E.SpaceHeating,
                fuels=(F.Electricity,),
                nrcan_rows=("electric",),
                new_equivalent=T.ElectricRadiator,
            ),
            X.SpaceHeatingHeatPump: ExistingTechnologySpec(
                description="heat pump",
                end_use=E.SpaceHeating,
                fuels=(F.Electricity,),
                nrcan_rows=("heat pump",),
                new_equivalent=T.AirSourceHeatPump,
            ),
            X.SpaceHeatingLPG: ExistingTechnologySpec(
                description="other (LPG)",
                end_use=E.SpaceHeating,
                fuels=(F.LiquifiedPretroleumGas,),
                nrcan_rows=("other",),
                new_equivalent=T.LPGFurnace,
            ),
            X.SpaceHeatingWood: ExistingTechnologySpec(
                description="wood",
                end_use=E.SpaceHeating,
                fuels=(F.Wood,),
                nrcan_rows=("wood",),
                new_equivalent=T.WoodStove,
            ),
            X.SpaceHeatingWoodElectric: ExistingTechnologySpec(
                description="dual wood-electric",
                end_use=E.SpaceHeating,
                fuels=(F.Wood, F.Electricity),
                nrcan_rows=("wood/electric",),
                new_equivalent=T.WoodStove,
            ),
            X.SpaceHeatingWoodOil: ExistingTechnologySpec(
                description="dual wood-oil",
                end_use=E.SpaceHeating,
                fuels=(F.Wood, F.Oil),
                nrcan_rows=("wood/heating oil",),
                new_equivalent=T.OilFurnace,
            ),
            X.SpaceHeatingNaturalGasElectric: ExistingTechnologySpec(
                description="dual natural gas-electric",
                end_use=E.SpaceHeating,
                fuels=(F.NaturalGas, F.Electricity),
                nrcan_rows=("natural gas/electric",),
                new_equivalent=T.NaturalGasFurnace,
            ),
            X.SpaceHeatingOilElectric: ExistingTechnologySpec(
                description="dual oil-electric",
                end_use=E.SpaceHeating,
                fuels=(F.Oil, F.Electricity),
                nrcan_rows=("heating oil/electric",),
                new_equivalent=T.OilFurnace,
            ),
            X.RoomAirConditioner: ExistingTechnologySpec(
                description="room air conditioning",
                end_use=E.SpaceCooling,
                fuels=(F.Electricity,),
                nrcan_rows=("room",),
                new_equivalent=T.RoomAirConditioner,
            ),
            X.CentralAirConditioner: ExistingTechnologySpec(
                description="central air conditioning",
                end_use=E.SpaceCooling,
                fuels=(F.Electricity,),
                nrcan_rows=("central",),
                new_equivalent=T.CentralAirConditioner,
            ),
            X.ElectricWaterHeater: ExistingTechnologySpec(
                description="electric",
                end_use=E.WaterHeating,
                fuels=(F.Electricity,),
                nrcan_rows=("electricity",),
                new_equivalent=T.ElectricWaterHeater,
            ),
            X.NaturalGasWaterHeater: ExistingTechnologySpec(
                description="natural gas",
                end_use=E.WaterHeating,
                fuels=(F.NaturalGas,),
                nrcan_rows=("natural gas",),
                new_equivalent=T.NaturalGasWaterHeater,
            ),
            X.OilWaterHeater: ExistingTechnologySpec(
                description="oil",
                end_use=E.WaterHeating,
                fuels=(F.Oil,),
                nrcan_rows=("heating oil",),
                new_equivalent=T.OilWaterHeater,
            ),
            X.LPGWaterHeater: ExistingTechnologySpec(
                description="other (LPG)",
                end_use=E.WaterHeating,
                fuels=(F.LiquifiedPretroleumGas,),
                nrcan_rows=("other",),
                new_equivalent=T.LPGWaterHeater,
            ),
            X.WoodWaterHeater: ExistingTechnologySpec(
                description="wood",
                end_use=E.WaterHeating,
                fuels=(F.Wood,),
                nrcan_rows=("wood",),
                # The AEO has no wood water heater: the previous module took the
                # wood stove's class (lifetime) and fixed cost
                new_equivalent=T.WoodStove,
            ),
            X.IncandescentBulb: ExistingTechnologySpec(
                description="incandescent",
                end_use=E.Lighting,
                fuels=(F.Electricity,),
                new_equivalent=T.IncandescentBulb,
                lamp="inc",
            ),
            X.HalogenBulb: ExistingTechnologySpec(
                description="halogen",
                end_use=E.Lighting,
                fuels=(F.Electricity,),
                new_equivalent=T.HalogenBulb,
                lamp="hal",
            ),
            X.CompactFluorescentBulb: ExistingTechnologySpec(
                description="compact fluorescent",
                end_use=E.Lighting,
                fuels=(F.Electricity,),
                new_equivalent=T.CompactFluorescentBulb,
                lamp="cfl",
            ),
            X.LEDBulb: ExistingTechnologySpec(
                description="led",
                end_use=E.Lighting,
                fuels=(F.Electricity,),
                new_equivalent=T.LEDBulb,
                lamp="led",
            ),
            X.LinearFluorescentLamp: ExistingTechnologySpec(
                description="linear fluorescent",
                end_use=E.Lighting,
                fuels=(F.Electricity,),
                new_equivalent=T.LinearFluorescentLamp,
                lamp="t12",
            ),
            X.Refrigerator: ExistingTechnologySpec(
                description="refrigerators",
                end_use=E.Refrigerators,
                fuels=(F.Electricity,),
                nrcan_rows=("refrigerator",),
                new_equivalent=T.Refrigerator,
            ),
            X.Freezer: ExistingTechnologySpec(
                description="freezers",
                end_use=E.Freezers,
                fuels=(F.Electricity,),
                nrcan_rows=("freezer",),
                new_equivalent=T.Freezer,
            ),
            X.DishWasher: ExistingTechnologySpec(
                description="dish washers",
                end_use=E.DishWashers,
                fuels=(F.Electricity,),
                nrcan_rows=("dishwasher",),
                new_equivalent=T.DishWasher,
            ),
            X.ClothesWasher: ExistingTechnologySpec(
                description="clothes washers",
                end_use=E.ClothesWashers,
                fuels=(F.Electricity,),
                nrcan_rows=("clothes washer",),
                new_equivalent=T.ClothesWasher,
            ),
            X.ElectricClothesDryer: ExistingTechnologySpec(
                description="electric clothes dryers",
                end_use=E.ClothesDryers,
                fuels=(F.Electricity,),
                nrcan_rows=("clothes dryer",),
                new_equivalent=T.ElectricClothesDryer,
            ),
            X.NaturalGasClothesDryer: ExistingTechnologySpec(
                description="natural gas clothes dryers",
                end_use=E.ClothesDryers,
                fuels=(F.NaturalGas,),
                nrcan_rows=("clothes dryer",),
                new_equivalent=T.NaturalGasClothesDryer,
            ),
            X.ElectricCookingRange: ExistingTechnologySpec(
                description="electric cooking ranges",
                end_use=E.CookingRanges,
                fuels=(F.Electricity,),
                nrcan_rows=("range",),
                new_equivalent=T.ElectricCookingRange,
            ),
            X.NaturalGasCookingRange: ExistingTechnologySpec(
                description="natural gas cooking ranges",
                end_use=E.CookingRanges,
                fuels=(F.NaturalGas,),
                nrcan_rows=("range",),
                new_equivalent=T.NaturalGasCookingRange,
            ),
            X.OtherAppliances: ExistingTechnologySpec(
                description="other electrical appliances and devices",
                end_use=E.OtherAppliances,
                fuels=(F.Electricity,),
                nrcan_rows=("other appliances",),
            ),
        }
        return SPECS[self]


def technologies_for(end_uses: tuple[ResidentialEndUse, ...]) -> list[NewTechnology]:
    """
    New technologies that can serve one of `end_uses`, in catalog order.

    Examples
    --------
    >>> [t.value for t in technologies_for((ResidentialEndUse.SpaceCooling,))][:3]
    ['air-source heat pump', 'air-source heat pump high efficiency', 'geo-exchange heat pump']
    """
    return [t for t in NewTechnology if set(t.end_uses()) & set(end_uses)]

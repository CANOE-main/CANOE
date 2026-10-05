"""
Catalog of the new residential technologies.

Users choose technologies by their readable name (`NewTechnology`, e.g.
"air-source heat pump") in the `new_technologies` list of each end
use table. This catalog holds the end uses each technology can serve; its parameters
(fuel, AEO equipment, costs) are added with the Temoa objects.
"""

from enum import StrEnum

from .end_uses import ResidentialEndUse


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
        T = NewTechnology
        E = ResidentialEndUse
        END_USES: dict[NewTechnology, tuple[ResidentialEndUse, ...]] = {
            **{
                t: (E.SpaceHeating,)
                for t in (
                    T.ElectricRadiator,
                    T.NaturalGasFurnace,
                    T.NaturalGasFurnaceHighEfficiency,
                    T.NaturalGasBoiler,
                    T.NaturalGasBoilerHighEfficiency,
                    T.OilFurnace,
                    T.OilFurnaceHighEfficiency,
                    T.OilBoiler,
                    T.OilBoilerHighEfficiency,
                    T.LPGFurnace,
                    T.LPGFurnaceHighEfficiency,
                    T.WoodStove,
                    T.WoodStoveHighEfficiency,
                )
            },
            **{
                t: (E.SpaceHeating, E.SpaceCooling)
                for t in (
                    T.AirSourceHeatPump,
                    T.AirSourceHeatPumpHighEfficiency,
                    T.GeoExchangeHeatPump,
                    T.GeoExchangeHeatPumpHighEfficiency,
                    T.NaturalGasHeatPump,
                )
            },
            **{
                t: (E.SpaceCooling,)
                for t in (
                    T.CentralAirConditioner,
                    T.CentralAirConditionerHighEfficiency,
                    T.RoomAirConditioner,
                    T.RoomAirConditionerHighEfficiency,
                )
            },
            **{
                t: (E.WaterHeating,)
                for t in (
                    T.ElectricWaterHeater,
                    T.ElectricWaterHeaterHighEfficiency,
                    T.HeatPumpWaterHeater,
                    T.HeatPumpWaterHeaterHighEfficiency,
                    T.NaturalGasWaterHeater,
                    T.NaturalGasWaterHeaterHighEfficiency,
                    T.OilWaterHeater,
                    T.OilWaterHeaterHighEfficiency,
                    T.LPGWaterHeater,
                    T.LPGWaterHeaterHighEfficiency,
                    T.SolarWaterHeater,
                )
            },
            **{
                t: (E.Lighting,)
                for t in (
                    T.IncandescentBulb,
                    T.HalogenBulb,
                    T.CompactFluorescentBulb,
                    T.CompactFluorescentBulbHighEfficiency,
                    T.LEDBulb,
                    T.LEDBulbHighEfficiency,
                    T.LinearFluorescentLamp,
                )
            },
            T.Refrigerator: (E.Refrigerators,),
            T.RefrigeratorHighEfficiency: (E.Refrigerators,),
            T.Freezer: (E.Freezers,),
            T.FreezerHighEfficiency: (E.Freezers,),
            T.DishWasher: (E.DishWashers,),
            T.DishWasherHighEfficiency: (E.DishWashers,),
            T.ClothesWasher: (E.ClothesWashers,),
            T.ClothesWasherHighEfficiency: (E.ClothesWashers,),
            T.ElectricClothesDryer: (E.ClothesDryers,),
            T.ElectricClothesDryerHighEfficiency: (E.ClothesDryers,),
            T.NaturalGasClothesDryer: (E.ClothesDryers,),
            T.NaturalGasClothesDryerHighEfficiency: (E.ClothesDryers,),
            T.ElectricCookingRange: (E.CookingRanges,),
            T.NaturalGasCookingRange: (E.CookingRanges,),
            T.NaturalGasCookingRangeHighEfficiency: (E.CookingRanges,),
            T.LPGCookingRange: (E.CookingRanges,),
            T.LPGCookingRangeHighEfficiency: (E.CookingRanges,),
        }
        return END_USES[self]


def technologies_for(end_uses: tuple[ResidentialEndUse, ...]) -> list[NewTechnology]:
    """
    New technologies that can serve one of `end_uses`, in catalog order.

    Examples
    --------
    >>> [t.value for t in technologies_for((ResidentialEndUse.SpaceCooling,))][:3]
    ['air-source heat pump', 'air-source heat pump high efficiency', 'geo-exchange heat pump']
    """
    return [t for t in NewTechnology if set(t.end_uses()) & set(end_uses)]

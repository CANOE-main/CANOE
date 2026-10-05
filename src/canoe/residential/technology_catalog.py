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
        return _END_USES[self]


_T = NewTechnology
_E = ResidentialEndUse
_END_USES: dict[NewTechnology, tuple[ResidentialEndUse, ...]] = {
    **{
        t: (_E.SpaceHeating,)
        for t in (
            _T.ElectricRadiator,
            _T.NaturalGasFurnace,
            _T.NaturalGasFurnaceHighEfficiency,
            _T.NaturalGasBoiler,
            _T.NaturalGasBoilerHighEfficiency,
            _T.OilFurnace,
            _T.OilFurnaceHighEfficiency,
            _T.OilBoiler,
            _T.OilBoilerHighEfficiency,
            _T.LPGFurnace,
            _T.LPGFurnaceHighEfficiency,
            _T.WoodStove,
            _T.WoodStoveHighEfficiency,
        )
    },
    **{
        t: (_E.SpaceHeating, _E.SpaceCooling)
        for t in (
            _T.AirSourceHeatPump,
            _T.AirSourceHeatPumpHighEfficiency,
            _T.GeoExchangeHeatPump,
            _T.GeoExchangeHeatPumpHighEfficiency,
            _T.NaturalGasHeatPump,
        )
    },
    **{
        t: (_E.SpaceCooling,)
        for t in (
            _T.CentralAirConditioner,
            _T.CentralAirConditionerHighEfficiency,
            _T.RoomAirConditioner,
            _T.RoomAirConditionerHighEfficiency,
        )
    },
    **{
        t: (_E.WaterHeating,)
        for t in (
            _T.ElectricWaterHeater,
            _T.ElectricWaterHeaterHighEfficiency,
            _T.HeatPumpWaterHeater,
            _T.HeatPumpWaterHeaterHighEfficiency,
            _T.NaturalGasWaterHeater,
            _T.NaturalGasWaterHeaterHighEfficiency,
            _T.OilWaterHeater,
            _T.OilWaterHeaterHighEfficiency,
            _T.LPGWaterHeater,
            _T.LPGWaterHeaterHighEfficiency,
            _T.SolarWaterHeater,
        )
    },
    **{
        t: (_E.Lighting,)
        for t in (
            _T.IncandescentBulb,
            _T.HalogenBulb,
            _T.CompactFluorescentBulb,
            _T.CompactFluorescentBulbHighEfficiency,
            _T.LEDBulb,
            _T.LEDBulbHighEfficiency,
            _T.LinearFluorescentLamp,
        )
    },
    _T.Refrigerator: (_E.Refrigerators,),
    _T.RefrigeratorHighEfficiency: (_E.Refrigerators,),
    _T.Freezer: (_E.Freezers,),
    _T.FreezerHighEfficiency: (_E.Freezers,),
    _T.DishWasher: (_E.DishWashers,),
    _T.DishWasherHighEfficiency: (_E.DishWashers,),
    _T.ClothesWasher: (_E.ClothesWashers,),
    _T.ClothesWasherHighEfficiency: (_E.ClothesWashers,),
    _T.ElectricClothesDryer: (_E.ClothesDryers,),
    _T.ElectricClothesDryerHighEfficiency: (_E.ClothesDryers,),
    _T.NaturalGasClothesDryer: (_E.ClothesDryers,),
    _T.NaturalGasClothesDryerHighEfficiency: (_E.ClothesDryers,),
    _T.ElectricCookingRange: (_E.CookingRanges,),
    _T.NaturalGasCookingRange: (_E.CookingRanges,),
    _T.NaturalGasCookingRangeHighEfficiency: (_E.CookingRanges,),
    _T.LPGCookingRange: (_E.CookingRanges,),
    _T.LPGCookingRangeHighEfficiency: (_E.CookingRanges,),
}


def technologies_for(end_uses: tuple[ResidentialEndUse, ...]) -> list[NewTechnology]:
    """
    New technologies that can serve one of `end_uses`, in catalog order.

    Examples
    --------
    >>> [t.value for t in technologies_for((ResidentialEndUse.SpaceCooling,))][:3]
    ['air-source heat pump', 'air-source heat pump high efficiency', 'geo-exchange heat pump']
    """
    return [t for t in NewTechnology if set(t.end_uses()) & set(end_uses)]

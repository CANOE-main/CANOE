"""
Catalog of new commercial space heating and cooling technologies.

Users choose technologies by their readable name (`NewTechnology`, e.g.
"air-source heat pump") in the `new_technologies` list of each end use. This catalog
holds the rest: the fuel, the code used in technology names, and the AEO CDM (ktek)
technology that provides the efficiency, lifetime and costs for each end use the
technology can serve.
"""

from dataclasses import dataclass
from enum import StrEnum

from canoe.commercial.end_uses import CommercialEndUse
from canoe.common import CANOEFuel


class NewTechnology(StrEnum):
    AirSourceHeatPump = "air-source heat pump"
    GroundSourceHeatPump = "ground-source heat pump"
    GasEngineHeatPump = "gas engine-driven heat pump"
    ResidentialGasHeatPump = "residential-type gas heat pump"
    ElectricBoiler = "electric boiler"
    ElectricResistanceHeater = "electric resistance heater"
    GasFurnace = "gas furnace"
    GasBoiler = "gas boiler"
    OilFurnace = "oil furnace"
    OilBoiler = "oil boiler"
    RooftopAirConditioner = "rooftop air conditioner"
    WallWindowAirConditioner = "wall/window air conditioner"
    ResidentialCentralAirConditioner = "residential-type central air conditioner"


@dataclass(frozen=True)
class NewTechnologySpec:
    """
    Parameters
    ----------
    code : str
        Used in technology names, `C_{SPH|SPC|SPHC}_{code}-NEW`.
    fuel : CANOEFuel
        Input fuel.
    aeo_technologies : dict[CommercialEndUse, str]
        End uses the technology can serve -> AEO ktek `techname` with its parameters
        for that end use.
    """

    code: str
    fuel: CANOEFuel
    aeo_technologies: dict[CommercialEndUse, str]


_SPH = CommercialEndUse.SpaceHeating
_SPC = CommercialEndUse.SpaceCooling

NEW_TECHNOLOGIES: dict[NewTechnology, NewTechnologySpec] = {
    NewTechnology.AirSourceHeatPump: NewTechnologySpec(
        code="HP_AIR",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={
            _SPH: "rooftop_ashp-heat 2023 new standard",
            _SPC: "rooftop_ashp-cool 2023 new standard",
        },
    ),
    NewTechnology.GroundSourceHeatPump: NewTechnologySpec(
        code="HP_GEO",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={
            _SPH: "comm_gshp-heat 2022 typical",
            _SPC: "comm_gshp-cool 2022 typical",
        },
    ),
    NewTechnology.GasEngineHeatPump: NewTechnologySpec(
        code="HP_NG",
        fuel=CANOEFuel.NaturalGas,
        aeo_technologies={
            _SPH: "gas_eng-driven_rthp-heat 2022 typical",
            _SPC: "gas_eng-driven_rthp-cool 2022 typical",
        },
    ),
    NewTechnology.ResidentialGasHeatPump: NewTechnologySpec(
        code="HP_NG_RES",
        fuel=CANOEFuel.NaturalGas,
        aeo_technologies={
            _SPH: "res_type_gashp-heat 2020 typical",
            _SPC: "res_type_gashp-cool 2020 typical",
        },
    ),
    NewTechnology.ElectricBoiler: NewTechnologySpec(
        code="ELC_BLR",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={_SPH: "elec_boiler 2022 typical"},
    ),
    NewTechnology.ElectricResistanceHeater: NewTechnologySpec(
        code="ELC_RES",
        fuel=CANOEFuel.Electricity,
        # The trailing space is part of the AEO techname
        aeo_technologies={_SPH: "elec_res-heater 2022 large "},
    ),
    NewTechnology.GasFurnace: NewTechnologySpec(
        code="NG_FRN",
        fuel=CANOEFuel.NaturalGas,
        aeo_technologies={_SPH: "gas_furnace 2022 typical"},
    ),
    NewTechnology.GasBoiler: NewTechnologySpec(
        code="NG_BLR",
        fuel=CANOEFuel.NaturalGas,
        aeo_technologies={_SPH: "gas_boiler 2022 typical"},
    ),
    NewTechnology.OilFurnace: NewTechnologySpec(
        code="OIL_FRN",
        fuel=CANOEFuel.Oil,
        aeo_technologies={_SPH: "oil_furnace 2022 typical"},
    ),
    NewTechnology.OilBoiler: NewTechnologySpec(
        code="OIL_BLR",
        fuel=CANOEFuel.Oil,
        aeo_technologies={_SPH: "oil_boiler 2022 typical"},
    ),
    NewTechnology.RooftopAirConditioner: NewTechnologySpec(
        code="AC_ROOF",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={_SPC: "rooftop_ac 2023 new standard"},
    ),
    NewTechnology.WallWindowAirConditioner: NewTechnologySpec(
        code="AC_WALL",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={_SPC: "wall-window_room_ac 2022 typical"},
    ),
    NewTechnology.ResidentialCentralAirConditioner: NewTechnologySpec(
        code="AC_RES",
        fuel=CANOEFuel.Electricity,
        aeo_technologies={_SPC: "res_type_central_ac 2022 typical north"},
    ),
}


def technologies_for(end_use: CommercialEndUse) -> list[NewTechnology]:
    """New technologies that can serve `end_use`, in catalog order"""
    return [
        technology
        for technology, spec in NEW_TECHNOLOGIES.items()
        if end_use in spec.aeo_technologies
    ]

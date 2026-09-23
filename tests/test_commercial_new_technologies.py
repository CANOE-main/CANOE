import pandas as pd
import pytest

from canoe.commercial.end_uses import CommercialEndUse
from canoe.commercial.new_technologies import (
    build_new_technologies,
    new_technology_fuel_commodities,
)
from canoe.commercial.technology_catalog import NEW_TECHNOLOGIES, NewTechnology
from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier

ON = CANOEProvince.ONTARIO
QC = CANOEProvince.QUEBEC
SPH = CommercialEndUse.SpaceHeating
SPC = CommercialEndUse.SpaceCooling
PERIODS = [2025, 2030, 2035]
DATA_ID = DatasetIdentifier(CANOESector.Commercial, "TEST", "000")


def _params(
    technology: NewTechnology, end_uses: list[CommercialEndUse], **overrides: float
) -> pd.DataFrame:
    """One row per (end use, province) with simple values; `overrides` by column"""
    rows = [
        {
            "technology": technology,
            "end_use": end_use,
            "province": province,
            "fuel": NEW_TECHNOLOGIES[technology].fuel,
            "aeo_technology": NEW_TECHNOLOGIES[technology].aeo_technologies[end_use],
            "efficiency": 3.0 if end_use == SPH else 4.0,
            "life": 10.0,
            "investment_cost": 20.0,
            "fixed_cost": 0.5,
        }
        for end_use in end_uses
        for province in [ON, QC]
    ]
    df = pd.DataFrame(rows)
    for column, value in overrides.items():
        df[column] = value
    return df


def _acf(rows: list[tuple[CANOEProvince, CommercialEndUse, CANOEFuel]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"province": p, "end_use": eu.get_full_name(), "fuel": f, "acf": 0.2}
            for p, eu, f in rows
        ]
    )


class TestBuildNewTechnologies:
    def test_heat_pump_is_one_technology_with_two_outputs(self):
        (heat_pump,) = build_new_technologies(
            {NewTechnology.AirSourceHeatPump: [SPH, SPC]},
            _params(NewTechnology.AirSourceHeatPump, [SPH, SPC]),
            _acf(
                [(p, eu, CANOEFuel.Electricity) for p in [ON, QC] for eu in [SPH, SPC]]
            ),
            [ON, QC],
            PERIODS,
            DATA_ID,
        )
        assert heat_pump.name == "C_SPHC_HP_AIR-NEW"
        assert heat_pump.inputs == ["C_elc"]
        assert heat_pump.outputs == ["C_D_SPH", "C_D_SPC"]
        assert list(heat_pump.capacity_factor_limits) == ["C_D_SPH", "C_D_SPC"]
        heat_pump.validate()

    def test_technology_listed_under_one_end_use_serves_only_that_one(self):
        (heat_pump,) = build_new_technologies(
            {NewTechnology.AirSourceHeatPump: [SPH]},
            _params(NewTechnology.AirSourceHeatPump, [SPH]),
            _acf([(p, SPH, CANOEFuel.Electricity) for p in [ON, QC]]),
            [ON, QC],
            PERIODS,
            DATA_ID,
        )
        assert heat_pump.name == "C_SPH_HP_AIR-NEW"
        assert heat_pump.outputs == ["C_D_SPH"]

    def test_provinces_without_existing_stock_data_are_left_out(self):
        (furnace,) = build_new_technologies(
            {NewTechnology.GasFurnace: [SPH]},
            _params(NewTechnology.GasFurnace, [SPH]),
            _acf([(ON, SPH, CANOEFuel.NaturalGas)]),
            [ON, QC],
            PERIODS,
            DATA_ID,
        )
        (efficiency,) = furnace.efficiencies.values()
        assert {r["region"] for r in efficiency.values.to_records()} == {ON}
        assert furnace.lifetime is not None
        assert {r["region"] for r in furnace.lifetime.values.to_records()} == {ON}

    def test_technology_without_any_province_is_skipped(self):
        technologies = build_new_technologies(
            {NewTechnology.GasFurnace: [SPH]},
            _params(NewTechnology.GasFurnace, [SPH]),
            _acf([(ON, SPH, CANOEFuel.Electricity)]),
            [ON, QC],
            PERIODS,
            DATA_ID,
        )
        assert technologies == []

    def test_fixed_costs_only_while_the_vintage_is_alive(self):
        (boiler,) = build_new_technologies(
            {NewTechnology.ElectricBoiler: [SPH]},
            _params(NewTechnology.ElectricBoiler, [SPH]),
            _acf([(ON, SPH, CANOEFuel.Electricity)]),
            [ON],
            PERIODS,
            DATA_ID,
        )
        assert boiler.fixed_cost is not None
        alive = {
            (r["vintage"], r["period"]) for r in boiler.fixed_cost.values.to_records()
        }
        # 10-year life: each vintage pays for its own period and the next one
        assert alive == {
            (2025, 2025),
            (2025, 2030),
            (2030, 2030),
            (2030, 2035),
            (2035, 2035),
        }

    def test_technology_level_values_come_from_space_heating(self):
        params = _params(NewTechnology.GroundSourceHeatPump, [SPH, SPC])
        params.loc[params["end_use"].isin([SPC]), "fixed_cost"] = 0.9
        (heat_pump,) = build_new_technologies(
            {NewTechnology.GroundSourceHeatPump: [SPH, SPC]},
            params,
            _acf(
                [(p, eu, CANOEFuel.Electricity) for p in [ON, QC] for eu in [SPH, SPC]]
            ),
            [ON, QC],
            PERIODS,
            DATA_ID,
        )
        assert heat_pump.fixed_cost is not None
        costs = [r["value"] for r in heat_pump.fixed_cost.values.to_records()]
        assert costs == pytest.approx([0.5] * len(costs))


class TestNewTechnologyFuelCommodities:
    def test_one_commodity_per_fuel(self):
        commodities = new_technology_fuel_commodities(
            {
                NewTechnology.AirSourceHeatPump: [SPH],
                NewTechnology.ElectricBoiler: [SPH],
                NewTechnology.GasFurnace: [SPH],
            },
            DATA_ID,
        )
        assert [c.name for c in commodities] == ["C_elc", "C_ng"]

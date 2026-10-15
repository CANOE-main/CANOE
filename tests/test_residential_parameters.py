"""
Parameters of the residential sector on small synthetic data: the rules of each end
use group (`space_heating`, `space_cooling`, `water_heating`, `appliances`,
`lighting`), the existing stock shared pieces and the new AEO technologies.

Values against the previous module are checked on the real data against the
reference database, not here.
"""

import pandas as pd
import pytest
from canoe_schema.v4_0 import OperatorCode

from canoe.common import CANOEFuel, CANOEProvince
from canoe.common.census_divisions import USCensusDivision
from canoe.residential.appliances import appliance_stock
from canoe.residential.end_uses import ResidentialEndUse
from canoe.residential.existing_stock import (
    capacity_factor_band,
    existing_technology_parameters,
    existing_vintages,
)
from canoe.residential.lighting import aeo_lamp_value, lighting_stock
from canoe.residential.new_technologies import new_technology_parameters
from canoe.residential.space_cooling import space_cooling_stock
from canoe.residential.space_heating import space_heating_stock, system_heat
from canoe.residential.technology_catalog import ExistingTechnology, NewTechnology
from canoe.residential.water_heating import water_heating_stock

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
PERIODS = [2025, 2030, 2035]
X = ExistingTechnology
E = ResidentialEndUse


def _frame(rows: list[tuple[object, ...]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _common(technologies: list[ExistingTechnology], lifetime: float = 12.0):
    """Vintages, lifetime and fixed cost (1.0) of `technologies`"""
    return (
        existing_vintages({t: lifetime for t in technologies}, PERIODS[0], 5),
        _frame([(t, lifetime) for t in technologies], ["technology", "lifetime"]),
        _frame([(t, 1.0) for t in technologies], ["technology", "cost"]),
    )


def _rows(df: pd.DataFrame, **filters: object) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for column, value in filters.items():
        mask &= df[column].isin([value])
    return df.loc[mask]


class TestExistingStock:
    def test_band_is_95_to_100_percent(self):
        band = capacity_factor_band(
            _frame([(X.Freezer, 0.2)], ["technology", "factor"])
        )
        assert list(zip(band["operator"], band["factor"])) == [
            (OperatorCode.GE, pytest.approx(0.19)),
            (OperatorCode.LE, 0.2),
        ]

    def test_stock_below_tolerance_or_without_efficiency_is_left_out(self):
        vintages, lifetime, fixed_cost = _common([X.Freezer, X.Refrigerator])
        parameters = existing_technology_parameters(
            stock=_frame(
                [
                    (ON, X.Freezer, 3.0),
                    (QC, X.Freezer, 0.05),
                    (ON, X.Refrigerator, 3.0),
                ],
                ["region", "technology", "stock"],
            ),
            efficiency=_frame(
                [
                    (r, X.Freezer, v, CANOEFuel.Electricity, 0.5)
                    for r in (ON, QC)
                    for v in vintages["vintage"].unique()
                ],
                ["region", "technology", "vintage", "fuel", "efficiency"],
            ),
            capacity_factor=_frame(
                [(ON, X.Freezer, 0.15)], ["region", "technology", "factor"]
            ),
            vintages=vintages,
            lifetime=lifetime,
            fixed_cost=fixed_cost,
            provinces=[ON, QC],
            model_periods=PERIODS,
            capacity_tolerance=0.1,
            efficiency_notes="",
            existing_capacity_notes="",
            capacity_factor_notes="",
            lifetime_notes="",
            fixed_cost_notes="",
        )
        capacity = parameters.existing_capacity
        # Freezers in Ontario only (Quebec below the tolerance); refrigerators have
        # stock but no efficiency
        assert set(zip(capacity["region"], capacity["technology"])) == {(ON, X.Freezer)}
        assert capacity["capacity"].sum() == pytest.approx(3.0)
        # Lifetime 12: vintages 2015, 2020, 2024; fixed costs while alive
        alive = _rows(parameters.fixed_cost, region=ON, technology=X.Freezer)
        assert sorted(zip(alive["vintage"], alive["period"])) == [
            (2015, 2025),
            (2020, 2025),
            (2020, 2030),
            (2024, 2025),
            (2024, 2030),
            (2024, 2035),
        ]


class TestSpaceHeating:
    def _stock(self):
        systems = [
            "natural gas – medium efficiency",
            "natural gas – high efficiency",
            "wood/electric",
        ]
        energy_use = _frame(
            [(ON, systems[0], 10.0), (ON, systems[1], 30.0), (ON, systems[2], 4.0)],
            ["province", "system", "energy_use"],
        )
        stock = _frame(
            [(ON, systems[0], 100.0), (ON, systems[1], 300.0), (ON, systems[2], 50.0)],
            ["province", "system", "stock"],
        )
        efficiencies = _frame(
            [
                (ON, systems[0], None, 0.8),
                (ON, systems[1], None, 0.9),
                (ON, "wood/electric", "electricity", 1.0),
                (ON, "wood/electric", "wood", 0.5),
            ],
            ["province", "system", "fuel", "efficiency"],
        )
        technologies = [X.SpaceHeatingNaturalGas, X.SpaceHeatingWoodElectric]
        vintages, lifetime, fixed_cost = _common(technologies)
        return (
            energy_use,
            efficiencies,
            space_heating_stock(
                energy_use,
                stock,
                efficiencies,
                vintages,
                lifetime,
                fixed_cost,
                [ON],
                PERIODS,
                0.1,
                2022,
            ),
        )

    def test_dual_systems_heat_with_their_first_fuel(self):
        energy_use, efficiencies, _ = self._stock()
        heat = system_heat(energy_use, efficiencies).set_index("system")["heat"]
        assert heat["wood/electric"] == pytest.approx(4.0 * 0.5)

    def test_efficiencies_weighted_by_energy_use_or_by_fuel(self):
        _, _, heating = self._stock()
        efficiency = heating.parameters.efficiency
        gas = _rows(efficiency, technology=X.SpaceHeatingNaturalGas)
        assert (
            list(gas["efficiency"]) == [pytest.approx((10 * 0.8 + 30 * 0.9) / 40)] * 3
        )
        dual = _rows(efficiency, technology=X.SpaceHeatingWoodElectric)
        assert set(zip(dual["fuel"], dual["efficiency"])) == {
            (CANOEFuel.Electricity, 1.0),
            (CANOEFuel.Wood, 0.5),
        }

    def test_capacity_factor_and_demand_are_the_heat_delivered(self):
        _, _, heating = self._stock()
        factor = heating.capacity_factor.set_index("technology")["factor"]
        assert factor[X.SpaceHeatingNaturalGas] == pytest.approx(35 / 400)
        assert heating.base_demand["demand"].sum() == pytest.approx(35 + 2)


class TestSpaceCooling:
    def test_vintages_take_the_stock_efficiency_of_their_year(self):
        technologies = [X.CentralAirConditioner]
        vintages, lifetime, fixed_cost = _common(technologies, lifetime=13)
        cooling = space_cooling_stock(
            _frame([(ON, "central", 2.0)], ["province", "system", "energy_use"]),
            _frame([(ON, "central", 100.0)], ["province", "system", "stock"]),
            _frame(
                [
                    (ON, "central", kind, "SEER", year, value)
                    for kind in ("stock", "new unit")
                    for year, value in ((2015, 10.0), (2020, 12.0), (2022, 13.0))
                ],
                ["province", "system", "kind", "metric", "year", "efficiency"],
            ),
            vintages,
            lifetime,
            fixed_cost,
            [ON],
            PERIODS,
            0.1,
            2022,
        )
        efficiency = cooling.parameters.efficiency.set_index("vintage")["efficiency"]
        # 2024 is past the last year of the table (2022)
        assert efficiency.to_dict() == {
            2015: pytest.approx(10 * 0.293),
            2020: pytest.approx(12 * 0.293),
            2024: pytest.approx(13 * 0.293),
        }
        assert cooling.base_demand["demand"].sum() == pytest.approx(2 * 13 * 0.293)


class TestWaterHeating:
    def test_hot_water_is_energy_use_times_efficiency(self):
        technologies = [X.ElectricWaterHeater]
        vintages, lifetime, fixed_cost = _common(technologies)
        water = water_heating_stock(
            _frame([(ON, "electricity", 9.0)], ["province", "source", "energy_use"]),
            _frame([(ON, "electricity", 100.0)], ["province", "source", "stock"]),
            _frame(
                [
                    (aeo_class, 5, 0.9)
                    for aeo_class in (
                        "ELEC_WH",
                        "NG_WH",
                        "DIST_WH",
                        "LPG_WH",
                        "WOOD_HT",
                    )
                ],
                ["equipment_class", "end_use", "base_efficiency"],
            ),
            vintages,
            lifetime,
            fixed_cost,
            [ON],
            PERIODS,
            0.1,
            2022,
        )
        # The previous module used the energy use
        assert water.base_demand["demand"].sum() == pytest.approx(9 * 0.9)
        assert water.capacity_factor["factor"].iloc[0] == pytest.approx(9 * 0.9 / 100)


class TestAppliances:
    def _stock(self):
        technologies = [
            t
            for t in ExistingTechnology
            if t.spec().end_use.is_appliance() and t != X.OtherAppliances
        ]
        vintages, lifetime, fixed_cost = _common(technologies)
        stock = _frame(
            [
                (ON, "freezer", "electricity", 1000.0),
                (ON, "other appliances", "electricity", 5000.0),
                (ON, "range", "electricity", 2000.0),
                (ON, "range", "natural gas", 500.0),
            ],
            ["province", "appliance", "fuel", "stock"],
        )
        return appliance_stock(
            _frame(
                [(ON, "freezer", 0.6), (ON, "other appliances", 2.0)],
                ["province", "appliance", "energy_use"],
            ),
            stock,
            _frame(
                [
                    (appliance, fuel, value)
                    for appliance in ("range", "clothes dryer")
                    for fuel, value in (("electricity", 500.0), ("natural gas", 1000.0))
                ],
                ["appliance", "fuel", "unit_consumption"],
            ),
            0.15,
            vintages,
            lifetime,
            fixed_cost,
            [ON],
            PERIODS,
            0.1,
            2022,
        )

    def test_demands_are_stock_in_use(self):
        demand = self._stock().stock.base_demand.set_index("end_use")["demand"]
        assert demand[E.Freezers] == pytest.approx(1.0 * 0.15)
        assert demand[E.CookingRanges] == pytest.approx(2.5 * 0.15)
        assert demand[E.OtherAppliances] == pytest.approx(5.0 * 0.15)

    def test_efficiencies(self):
        appliances = self._stock()
        efficiency = appliances.stock.parameters.efficiency
        freezer = _rows(efficiency, technology=X.Freezer)["efficiency"]
        assert list(freezer) == [pytest.approx(1.0 * 0.15 / 0.6)] * 3
        gas_range = _rows(efficiency, technology=X.NaturalGasCookingRange)["efficiency"]
        assert list(gas_range) == [pytest.approx(0.15 / (1000 * 3.6e-9 * 1e6))] * 3
        assert appliances.other_appliances_efficiency["efficiency"].iloc[
            0
        ] == pytest.approx(5.0 * 0.15 / 2.0)


class TestLighting:
    def test_aeo_values_of_the_latest_year_before_or_the_existing_stock(self):
        aeo = _frame(
            [
                ("led", "efficacy", "lm/W", pd.NA, 80.0),
                ("led", "efficacy", "lm/W", 2022, 90.0),
                ("led", "efficacy", "lm/W", 2030, 100.0),
                ("cfl", "efficacy", "lm/W", 2022, 60.0),
                ("cfl", "efficacy", "lm/W", 2040, 70.0),
            ],
            ["lamp", "metric", "units", "year", "value"],
        ).astype({"year": "Int64"})
        assert aeo_lamp_value(aeo, "led", "efficacy", None) == 80.0
        assert aeo_lamp_value(aeo, "led", "efficacy", 2030) == 90.0
        assert aeo_lamp_value(aeo, "led", "efficacy", 2035) == 100.0
        # No LED value in 2040 (the year before 2045): the existing stock's
        assert aeo_lamp_value(aeo, "led", "efficacy", 2045) == 80.0

    def test_oldest_vintage_keeps_the_shares_of_the_oldest_vintages(self):
        lamps = ["inc", "hal", "cfl", "led", "t12"]
        aeo = _frame(
            [
                (lamp, metric, "", pd.NA, value)
                for lamp in lamps
                for metric, value in (
                    ("efficacy", 50.0),
                    # 15 years on 2/24 of the year: vintages 2015, 2020, 2024
                    ("lamp_life", 15 * 8760 / 12),
                    ("cost_maintain", 1.0),
                )
            ],
            ["lamp", "metric", "units", "year", "value"],
        ).astype({"year": "Int64"})
        shares = _frame(
            [(lamp, 0.2, 0.2, f"type {lamp}", pd.NA) for lamp in lamps],
            [
                "lamp",
                "single_family",
                "multi_family",
                "statcan_category",
                "oldest_vintage",
            ],
        )
        shares.loc[shares["lamp"] == "led", "oldest_vintage"] = 2020
        lighting = lighting_stock(
            _frame([(ON, 10.0)], ["province", "energy_use"]),
            _frame(
                [(ON, "single detached", 1.0)], ["province", "building_type", "share"]
            ),
            aeo,
            shares.astype({"oldest_vintage": "Int64"}),
            _frame(
                [
                    (ON, f"type {lamp}", year, 50.0)
                    for lamp in lamps
                    for year in (2017, 2019)
                ],
                ["province", "light_type", "year", "percent"],
            ),
            _frame([(ON, 1.0)], ["region", "growth"]),
            [],
            1 / 12,
            1.0,
            [ON],
            PERIODS,
            5,
            {2025: 2030, 2030: 2035, 2035: 2040},
            0.1,
            2022,
        )
        capacity = lighting.stock.parameters.existing_capacity
        # Each lamp: 0.2 x 10 PJ x 50 x 0.0317 Glmy/PJ / (1/12) = 19.02 Glm
        total = 0.2 * 10 * 50 * 0.0317 * 12
        incandescent = _rows(capacity, technology=X.IncandescentBulb)
        assert incandescent["capacity"].sum() == pytest.approx(total)
        led = _rows(capacity, technology=X.LEDBulb)
        assert sorted(led["vintage"]) == [2020, 2024]
        assert led["capacity"].sum() == pytest.approx(total * 2 / 3)


class TestNewTechnologies:
    def _parameters(self, selected: dict[NewTechnology, list[ResidentialEndUse]]):
        equipment = _frame(
            [
                ("ELEC_HP2", 1, 2, 2020, 2050, 2.5, 3000.0),
                ("ELEC_HP2", 2, 2, 2020, 2050, 15.0, 3000.0),
                ("FREZ_C1", 9, 11, 2020, 2050, 300.0, 500.0),
            ],
            [
                "equipment",
                "end_use",
                "census_division",
                "first_year",
                "last_year",
                "efficiency",
                "replacement_cost",
            ],
        )
        classes = _frame(
            [
                ("ELEC_HP", 1, 1.8, "COP"),
                ("ELEC_HP", 2, 10.0, "EER"),
                ("FREZ", 9, 400.0, "kWh/yr"),
            ],
            ["equipment_class", "end_use", "base_efficiency", "efficiency_metric"],
        )
        return new_technology_parameters(
            selected,
            equipment,
            classes,
            {ON: USCensusDivision.MiddleAtlantic, QC: USCensusDivision.MiddleAtlantic},
            _frame(
                [
                    (ON, X.SpaceHeatingHeatPump, 0.04),
                    (QC, X.SpaceHeatingHeatPump, 0.05),
                    (ON, X.CentralAirConditioner, 0.02),
                    (ON, X.Freezer, 0.15),
                ],
                ["region", "technology", "factor"],
            ),
            _frame(
                [(ON, X.Freezer, 2015, CANOEFuel.Electricity, 0.5)],
                ["region", "technology", "vintage", "fuel", "efficiency"],
            ),
            {"ELEC_HP": 15.0, "FREZ": 11.0},
            1.0,
            [ON, QC],
            PERIODS,
            {2025: 2030, 2030: 2035, 2035: 2040},
        )

    def test_heat_pump_costs_and_efficiencies(self):
        parameters = self._parameters(
            {NewTechnology.AirSourceHeatPump: [E.SpaceHeating, E.SpaceCooling]}
        )
        cost = _rows(parameters.investment_cost, region=ON, vintage=2025)["cost"]
        # Twice the replacement cost (split between heating and cooling), $/unit
        # to M$/kunit
        assert cost.iloc[0] == pytest.approx(2 * 3000 * 0.001)
        efficiency = _rows(parameters.efficiency, region=ON, vintage=2025)
        assert dict(zip(efficiency["end_use"], efficiency["efficiency"])) == {
            E.SpaceHeating: 2.5,
            E.SpaceCooling: pytest.approx(15 * 0.293),
        }

    def test_capacity_factors_of_the_equivalents_where_they_have_one(self):
        parameters = self._parameters(
            {NewTechnology.AirSourceHeatPump: [E.SpaceHeating, E.SpaceCooling]}
        )
        factors = _rows(
            parameters.capacity_factor, vintage=2025, operator=OperatorCode.LE
        )
        assert set(zip(factors["region"], factors["end_use"], factors["factor"])) == {
            (ON, E.SpaceHeating, 0.04),
            (QC, E.SpaceHeating, 0.05),
            (ON, E.SpaceCooling, 0.02),
        }

    def test_heat_pump_listed_for_heating_only(self):
        parameters = self._parameters(
            {NewTechnology.AirSourceHeatPump: [E.SpaceHeating]}
        )
        assert set(parameters.efficiency["end_use"]) == {E.SpaceHeating}

    def test_appliances_improve_the_existing_efficiency(self):
        parameters = self._parameters({NewTechnology.Freezer: [E.Freezers]})
        efficiency = _rows(parameters.efficiency, region=ON)["efficiency"]
        # kWh/yr: 300 new versus 400 base is an improvement of 4/3
        assert list(efficiency) == [pytest.approx(0.5 * 400 / 300)] * 3
        # No existing freezer efficiency in Quebec: no efficiency there
        assert _rows(parameters.efficiency, region=QC).empty

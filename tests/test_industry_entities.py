import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema
from canoe_schema.v4_0 import OperatorCode

from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.industry.entities import (
    FREE_OTHER_SUPPLY,
    SOURCE_COMMODITY,
    build_free_other_fuel_supply,
    build_subsector_demand,
    build_subsector_technology,
    industry_fuel_imports,
)
from canoe.industry.subsectors import IndustrySubsector

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
ELC, NG, OTH = CANOEFuel.Electricity, CANOEFuel.NaturalGas, CANOEFuel.Other
CEMENT, MINING = IndustrySubsector.Cement, IndustrySubsector.Mining
PERIODS = [2025, 2030]
DATA_ID = DatasetIdentifier(CANOESector.Industry, "HR", "000")


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the rows canoe-base would have seeded"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("INDHR000",), ("INDHRON000",), ("INDHRQC000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        [(0, 2025), (1, 2030), (2, 2035)],
    )
    return db


def _demand() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (ON, 2025, CEMENT, 10.0),
            (ON, 2030, CEMENT, 11.0),
            (QC, 2025, CEMENT, 0.0),
            (ON, 2025, MINING, 99.0),
        ],
        columns=["region", "period", "subsector", "demand"],
    )


def _input_splits(with_other: bool = False) -> pd.DataFrame:
    rows = [
        (ON, 2025, CEMENT, ELC, 0.2),
        (ON, 2025, CEMENT, NG, 0.8 if not with_other else 0.7),
        (ON, 2025, CEMENT, CANOEFuel.Coal, 0.0),
        (QC, 2025, CEMENT, ELC, 1.0),
        (ON, 2025, MINING, NG, 1.0),
    ]
    if with_other:
        rows.append((ON, 2025, CEMENT, OTH, 0.1))
    return pd.DataFrame(
        rows, columns=["region", "period", "subsector", "fuel", "split"]
    )


def _cement(input_splits: pd.DataFrame, fuels: list[CANOEFuel]):
    return build_subsector_technology(
        CEMENT,
        input_splits,
        fuels,
        [ON, QC],
        PERIODS,
        OperatorCode.GE,
        split_notes="CEUD shares",
        data_id=DATA_ID,
    )


class TestDemand:
    def test_writes_positive_demand_of_its_subsector(self, db: sqlite3.Connection):
        build_subsector_demand(
            CEMENT, _demand(), [ON, QC], PERIODS, notes="GDP", data_id=DATA_ID
        ).build(db)
        assert db.execute(
            "SELECT region, period, commodity, demand FROM demand"
        ).fetchall() == [
            ("ON", 2025, "I_D_CEMENT", 10.0),
            ("ON", 2030, "I_D_CEMENT", 11.0),
        ]
        assert db.execute(
            "SELECT name, flag, description FROM commodity"
        ).fetchall() == [("I_D_CEMENT", "d", "demand for cement energy")]


class TestSubsectorTechnology:
    def test_one_shared_technology_with_the_used_fuels(self, db: sqlite3.Connection):
        build_subsector_demand(
            CEMENT, _demand(), [ON, QC], PERIODS, notes="GDP", data_id=DATA_ID
        ).build(db)
        technology = _cement(_input_splits(), [ELC, NG, CANOEFuel.Coal])
        assert technology.fuels == [ELC, NG]
        technology.build(db)
        assert db.execute(
            "SELECT tech, unlim_cap, annual, description FROM technology"
        ).fetchall() == [("I_CEMENT", 1, 1, "energy use of the cement industry")]
        assert db.execute(
            "SELECT name, flag FROM commodity WHERE flag != 'd'"
        ).fetchall() == [
            ("I_elc", "p"),
            ("I_ng", "a"),
        ]
        assert db.execute(
            "SELECT region, period, input_comm, operator, proportion "
            + "FROM limit_tech_input_split_annual ORDER BY region, input_comm"
        ).fetchall() == [
            ("ON", 2025, "I_elc", "ge", 0.2),
            ("ON", 2025, "I_ng", "ge", 0.8),
            ("QC", 2025, "I_elc", "ge", 1.0),
        ]
        assert db.execute(
            "SELECT region, input_comm, vintage, output_comm, efficiency FROM efficiency "
            + "ORDER BY region, input_comm"
        ).fetchall() == [
            ("ON", "I_elc", 2025, "I_D_CEMENT", 1.0),
            ("ON", "I_ng", 2025, "I_D_CEMENT", 1.0),
            ("QC", "I_elc", 2025, "I_D_CEMENT", 1.0),
        ]

    def test_rejects_subsector_without_splits(self):
        with pytest.raises(ValueError, match="no inputs"):
            _cement(_input_splits(), [CANOEFuel.Coal])


class TestFuelImports:
    def test_other_fuels_are_not_imported(self):
        technology = _cement(_input_splits(with_other=True), [ELC, NG, OTH])
        imports = industry_fuel_imports([technology])
        assert [(i.fuel, i.provinces) for i in imports] == [
            (ELC, (ON, QC)),
            (NG, (ON,)),
        ]


class TestFreeOtherFuelSupply:
    def test_none_without_other_fuels(self):
        technology = _cement(_input_splits(), [ELC, NG])
        assert build_free_other_fuel_supply([technology], 5, DATA_ID) is None

    def test_supplies_other_fuels_where_used(self, db: sqlite3.Connection):
        build_subsector_demand(
            CEMENT, _demand(), [ON, QC], PERIODS, notes="GDP", data_id=DATA_ID
        ).build(db)
        technology = _cement(_input_splits(with_other=True), [ELC, NG, OTH])
        technology.build(db)
        supply = build_free_other_fuel_supply([technology], 5, DATA_ID)
        assert supply is not None
        supply.build(db)

        assert db.execute(
            "SELECT name, flag FROM commodity WHERE name IN (?, ?) ORDER BY flag",
            (SOURCE_COMMODITY, "I_oth"),
        ).fetchall() == [("I_oth", "a"), (SOURCE_COMMODITY, "s")]
        assert db.execute(
            "SELECT region, input_comm, vintage, output_comm, efficiency FROM efficiency "
            + "WHERE tech = ?",
            (FREE_OTHER_SUPPLY,),
        ).fetchall() == [("ON", SOURCE_COMMODITY, 2025, "I_oth", 1.0)]
        assert db.execute(
            "SELECT region, lifetime FROM lifetime_tech WHERE tech = ?",
            (FREE_OTHER_SUPPLY,),
        ).fetchall() == [("ON", 5.0)]
        # No cost and no emissions
        for table in (
            "cost_variable",
            "cost_fixed",
            "cost_invest",
            "emission_activity",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)

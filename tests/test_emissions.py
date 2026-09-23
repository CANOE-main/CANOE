import sqlite3

import pytest
from canoe_schema.sql import get_sql_schema

from canoe.common import (
    CANOEEmission,
    CANOEEmissionDeclaration,
    CANOEProvince,
    CANOESector,
    GlobalWarmingPotential,
)
from canoe.common.naming import DatasetIdentifier
from canoe.emissions import EmissionsConfig
from canoe.emissions import processing as emissions_processing

REGIONS = [CANOEProvince.ONTARIO, CANOEProvince.QUEBEC]
PERIODS = [2025, 2030]
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "003")
COMMERCIAL_GASES = [
    CANOEEmissionDeclaration(CANOESector.Commercial, emission)
    for emission in CANOEEmission
]


@pytest.fixture
def db() -> sqlite3.Connection:
    """Schema, regions, periods and one commercial gas furnace, before `init`"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.execute("INSERT INTO data_set (data_id) VALUES ('COMTEST')")
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        [(0, 2025), (1, 2030)],
    )
    db.executemany(
        "INSERT INTO commodity_label (commodity) VALUES (?)", [("C_ng",), ("C_D",)]
    )
    db.execute("INSERT INTO technology_label (tech) VALUES ('C_FRN')")
    db.execute(
        "INSERT INTO technology (tech, flag, sector, data_id) "
        "VALUES ('C_FRN', 'p', 'commercial', 'COMTEST')"
    )
    return db


def _write_activity(
    db: sqlite3.Connection, emission: str, activity: float, units: str = "kt/PJ"
) -> None:
    db.execute(
        "INSERT INTO emission_activity "
        "(region, emis_comm, input_comm, tech, vintage, output_comm, activity, units, data_id) "
        "VALUES ('ON', ?, 'C_ng', 'C_FRN', 2025, 'C_D', ?, ?, 'COMTEST')",
        (emission, activity, units),
    )


class TestInit:
    def test_registers_gases_and_co2_equivalent(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        commodities = db.execute("SELECT name, flag, data_id FROM commodity").fetchall()
        assert sorted(commodities) == [
            ("ch4", "e", "ELCHR003"),
            ("co2", "e", "ELCHR003"),
            ("co2e", "e", "ELCHR003"),
            ("n2o", "e", "ELCHR003"),
        ]
        assert db.execute("SELECT COUNT(*) FROM cost_emission").fetchone() == (0,)

    def test_registers_electricity_data_sets(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        data_sets = {row[0] for row in db.execute("SELECT data_id FROM data_set")}
        assert {"ELCHR003", "ELCHRON003", "ELCHRQC003"} <= data_sets

    def test_cost_of_co2_equivalent_in_every_region_and_period(
        self, db: sqlite3.Connection
    ):
        emissions_processing.init(
            db, EmissionsConfig(cost_of_co2e=0.05), REGIONS, PERIODS, DATA_ID
        )
        costs = db.execute(
            "SELECT region, period, emis_comm, cost, data_id FROM cost_emission"
        ).fetchall()
        assert sorted(costs) == [
            ("ON", 2025, "co2e", 0.05, "ELCHRON003"),
            ("ON", 2030, "co2e", 0.05, "ELCHRON003"),
            ("QC", 2025, "co2e", 0.05, "ELCHRQC003"),
            ("QC", 2030, "co2e", 0.05, "ELCHRQC003"),
        ]


class TestFinalize:
    def test_co2_equivalent_is_the_gwp_weighted_sum(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        _write_activity(db, "co2", 50.0)
        _write_activity(db, "ch4", 0.001)
        _write_activity(db, "n2o", 0.0001)
        emissions_processing.finalize(db, EmissionsConfig(), COMMERCIAL_GASES)

        ((activity, units, data_id),) = db.execute(
            "SELECT activity, units, data_id FROM emission_activity WHERE emis_comm = 'co2e'"
        ).fetchall()
        gwp = GlobalWarmingPotential.AR5_100.factors()
        expected = (
            50.0 * gwp[CANOEEmission.CO2]
            + 0.001 * gwp[CANOEEmission.CH4]
            + 0.0001 * gwp[CANOEEmission.N2O]
        )
        assert activity == pytest.approx(expected)
        assert (units, data_id) == ("kt/PJ", "COMTEST")

    def test_undeclared_emission_is_rejected(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        _write_activity(db, "co2", 50.0)
        with pytest.raises(ValueError, match="no module declared"):
            emissions_processing.finalize(db, EmissionsConfig(), [])

    def test_modules_cannot_write_co2_equivalents(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        _write_activity(db, "co2e", 50.0)
        with pytest.raises(ValueError, match="must only write the gases"):
            emissions_processing.finalize(db, EmissionsConfig(), COMMERCIAL_GASES)

    def test_gases_of_a_flow_must_share_units(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        _write_activity(db, "co2", 50.0, units="kt/PJ")
        _write_activity(db, "ch4", 1.0, units="t/PJ")
        with pytest.raises(ValueError, match="share units"):
            emissions_processing.finalize(db, EmissionsConfig(), COMMERCIAL_GASES)

    def test_declared_emission_without_rows_only_warns(self, db: sqlite3.Connection):
        emissions_processing.init(db, EmissionsConfig(), REGIONS, PERIODS, DATA_ID)
        emissions_processing.finalize(db, EmissionsConfig(), COMMERCIAL_GASES)
        assert db.execute("SELECT COUNT(*) FROM emission_activity").fetchone() == (0,)

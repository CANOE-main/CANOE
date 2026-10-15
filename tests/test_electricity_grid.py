import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GridLevel
from canoe.electricity.supply.entities import build_grid

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the rows the sectors would write"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("ELCHR000",), ("ELCHRON000",), ("ELCHRQC000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        [(i, p) for i, p in enumerate(PERIODS)],
    )
    db.executemany(
        "INSERT INTO commodity_label (commodity) VALUES (?)", [("C_elc",), ("I_elc",)]
    )
    return db


def _build(db: sqlite3.Connection, imports: list[CANOEFuelImport]):
    efficiencies = pd.DataFrame({"region": [ON, QC], "efficiency": [0.92, 0.926]})
    costs = pd.DataFrame(
        [
            (level, period, cost + i)
            for level, cost in (
                (GridLevel.Transmission, 6.0),
                (GridLevel.Distribution, 11.0),
            )
            for i, period in enumerate(PERIODS)
        ],
        columns=["level", "period", "cost"],
    )
    grid = build_grid(
        efficiencies,
        costs,
        imports,
        first_period=2025,
        lifetime=15,
        cost_notes="test",
        data_id=DATA_ID,
    )
    grid.build(db)
    return grid


def test_grid_chain(db: sqlite3.Connection):
    _ = _build(db, [])
    assert db.execute(
        "SELECT name, flag, units FROM commodity ORDER BY name"
    ).fetchall() == [
        ("E_elc_dem", "p", "PJ"),
        ("E_elc_dx", "p", "PJ"),
        ("E_elc_tx", "p", "PJ"),
    ]
    assert db.execute(
        "SELECT region, input_comm, tech, vintage, output_comm, efficiency "
        + "FROM efficiency ORDER BY tech, region"
    ).fetchall() == [
        ("ON", "E_elc_dx", "E_ELC_DX_to_DEM", 2025, "E_elc_dem", 1.0),
        ("QC", "E_elc_dx", "E_ELC_DX_to_DEM", 2025, "E_elc_dem", 1.0),
        ("ON", "E_elc_tx", "E_ELC_TX_to_DX", 2025, "E_elc_dx", 0.92),
        ("QC", "E_elc_tx", "E_ELC_TX_to_DX", 2025, "E_elc_dx", 0.926),
    ]
    assert db.execute(
        "SELECT tech, sector, unlim_cap, annual FROM technology ORDER BY tech"
    ).fetchall() == [
        ("E_ELC_DX_to_DEM", "electricity", 1, 0),
        ("E_ELC_TX_to_DX", "electricity", 1, 0),
    ]


def test_single_vintage_serves_every_period(db: sqlite3.Connection):
    _ = _build(db, [])
    assert db.execute(
        "SELECT DISTINCT tech, lifetime FROM lifetime_tech ORDER BY tech"
    ).fetchall() == [("E_ELC_DX_to_DEM", 15.0), ("E_ELC_TX_to_DX", 15.0)]
    assert db.execute(
        "SELECT period, vintage, cost, units FROM cost_variable "
        + "WHERE region = 'ON' AND tech = 'E_ELC_TX_to_DX' ORDER BY period"
    ).fetchall() == [
        (2025, 2025, 6.0, "M$/PJ"),
        (2030, 2025, 7.0, "M$/PJ"),
        (2035, 2025, 8.0, "M$/PJ"),
    ]


def test_delivery_to_each_sector_where_it_imports(db: sqlite3.Connection):
    imports = [
        CANOEFuelImport(CANOESector.Commercial, CANOEFuel.Electricity, (ON, QC)),
        CANOEFuelImport(CANOESector.Industry, CANOEFuel.Electricity, (QC,)),
    ]
    grid = _build(db, imports)
    assert [t.name for t in grid.deliveries] == ["E_C_ELC", "E_I_ELC"]
    assert db.execute(
        "SELECT region, input_comm, tech, output_comm, efficiency FROM efficiency "
        + "WHERE tech LIKE 'E\\__\\_ELC' ESCAPE '\\' ORDER BY tech, region"
    ).fetchall() == [
        ("ON", "E_elc_dem", "E_C_ELC", "C_elc", 1.0),
        ("QC", "E_elc_dem", "E_C_ELC", "C_elc", 1.0),
        ("QC", "E_elc_dem", "E_I_ELC", "I_elc", 1.0),
    ]
    # Labelled with the consuming sector, not annual (hourly balance), no cost
    assert db.execute(
        "SELECT tech, sector, unlim_cap, annual FROM technology "
        + "WHERE tech IN ('E_C_ELC', 'E_I_ELC') ORDER BY tech"
    ).fetchall() == [("E_C_ELC", "commercial", 1, 0), ("E_I_ELC", "industry", 1, 0)]
    assert (
        db.execute(
            "SELECT COUNT(*) FROM cost_variable WHERE tech IN ('E_C_ELC', 'E_I_ELC')"
        ).fetchone()[0]
        == 0
    )

import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema
from pydantic import ValidationError

from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GridLevel, StorageTechnology
from canoe.electricity.config import StorageConfig
from canoe.electricity.fleet import existing_storage, existing_storage_units
from canoe.electricity.generation.entities import GenerationNotes
from canoe.electricity.generation.parameters import (
    existing_processes,
    new_processes,
    process_investment_costs,
    process_om_costs,
)
from canoe.electricity.storage.entities import build_existing_storage, build_new_storage
from canoe.electricity.storage.parameters import storage_efficiencies
from canoe.electricity.supply.entities import build_grid

ON, AB = CANOEProvince.ONTARIO, CANOEProvince.ALBERTA
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]
NOTES = GenerationNotes(
    capacity="capacity", atb_costs="atb", coders_costs="coders",
    atb_efficiency="atb", cogeneration="cogeneration", vre_bin_costs="bins",
    vre_bin_limits="limits", vre_bin_capacity_factors="bin profiles",
    vre_capacity_factors="vre", hydro_capacity_factors="hydro", capture="capture",
)  # fmt: skip
BAT2, PUMP4 = StorageTechnology.Battery2h, StorageTechnology.PumpedHydro4h
LIFETIMES = {t: 100 if t.never_retires() else 15 for t in StorageTechnology}


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the grid the storage connects to"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("ELCHR000",), ("ELCHRON000",), ("ELCHRAB000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("AB",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, ?)",
        [
            (i, p, "e" if p < PERIODS[0] else "f")
            for i, p in enumerate([2020, 2024, *PERIODS])
        ],
    )
    build_grid(
        pd.DataFrame({"region": [ON, AB], "efficiency": [0.92, 0.92]}),
        pd.DataFrame(
            [(level, p, 1.0) for level in GridLevel for p in PERIODS],
            columns=["level", "period", "cost"],
        ),
        [],
        first_period=2025,
        lifetime=15,
        cost_notes="test",
        data_id=DATA_ID,
    ).build(db)
    return db


def _fleet() -> pd.DataFrame:
    # Two Alberta 1.75 h batteries (2 h), Ontario pumped hydro (3.5 h -> 4 h, never
    # retires), a flywheel (no technology) and a battery built in 2026 (left out)
    units = pd.DataFrame(
        {
            "region": [AB, AB, ON, ON, ON],
            "coders_type": [
                "storage_lithium",
                "storage_lithium",
                "storage_pump",
                "storage_flywheel",
                "storage_lithium",
            ],
            "facility": ["A", "B", "Beck Pump", "Guelph", "New"],
            "capacity": [20.0, 20.0, 174.0, 5.0, 50.0],
            "duration": [1.75, 1.75, 3.5, 0.1, 4.0],
            "start_year": [2020, 2020, 1957, 2016, 2026],
            "renewal_year": [2020, 2020, 2016, 2016, 2026],
        }
    )
    return existing_storage(
        existing_storage_units(units, [ON, AB], 2025, 5), LIFETIMES, 2025, 0.001
    )


def test_existing_storage_fleet():
    fleet = _fleet()
    assert [
        (r.short(), t.value, v, round(c, 3))
        for r, t, v, c in zip(
            fleet["region"], fleet["technology"], fleet["vintage"], fleet["capacity"]
        )
    ] == [("AB", "battery_2h", 2020, 0.04), ("ON", "pump_4h", 2024, 0.174)]


def test_storage_entities(db: sqlite3.Connection):
    fleet = _fleet()
    generic = pd.DataFrame(
        {"fixed_om": [59488.0, 16722.0], "variable_om": [0.0, 1.0]},
        index=pd.Index(["storage_lithium", "storage_pump"], name="coders_type"),
    )
    atb = pd.DataFrame(
        [
            ("Utility-Scale Battery Storage - 2Hr", parameter, year, value)
            for parameter, value in (("OCC", 900.0), ("Fixed O&M", 25.0))
            for year in (2022, 2030, 2035, 2040)
        ],
        columns=["display_name", "parameter", "year", "value"],
    )
    existing = existing_processes(fleet)
    new = new_processes([BAT2], [ON], {2025: 2030, 2030: 2035, 2035: 2040})
    technologies = [
        *build_existing_storage(
            fleet,
            storage_efficiencies(existing, 0.85, 0.8),
            process_om_costs(existing, generic, atb, LIFETIMES, PERIODS, 1.0, 1.0),
            LIFETIMES,
            NOTES,
            DATA_ID,
        ),
        *build_new_storage(
            storage_efficiencies(new, 0.85, 0.8),
            process_investment_costs(new, atb, 1.0),
            process_om_costs(new, generic, atb, LIFETIMES, PERIODS, 1.0, 1.0),
            LIFETIMES,
            NOTES,
            DATA_ID,
        ),
    ]
    for technology in technologies:
        technology.build(db)

    assert db.execute(
        "SELECT tech, flag, reserve, description FROM technology"
        + " WHERE flag = 'ps' ORDER BY tech"
    ).fetchall() == [
        (
            "E_BAT_2H-EXS",
            "ps",
            1,
            "utility-scale lithium-ion battery storage with 2-hour capacity - existing",
        ),
        (
            "E_BAT_2H-NEW",
            "ps",
            1,
            "utility-scale lithium-ion battery storage with 2-hour capacity - new",
        ),
        (
            "E_PUMP_4H-EXS",
            "ps",
            1,
            "hydroelectric pumped storage with 4-hour capacity - existing",
        ),
    ]
    # Round trip on the transmission level
    assert db.execute(
        "SELECT DISTINCT tech, input_comm, output_comm, efficiency FROM efficiency"
        + " WHERE tech LIKE 'E\\_%H-%' ESCAPE '\\' ORDER BY tech"
    ).fetchall() == [
        ("E_BAT_2H-EXS", "E_elc_tx", "E_elc_tx", 0.85),
        ("E_BAT_2H-NEW", "E_elc_tx", "E_elc_tx", 0.85),
        ("E_PUMP_4H-EXS", "E_elc_tx", "E_elc_tx", 0.8),
    ]
    assert db.execute(
        "SELECT d.region, d.tech, d.duration, l.lifetime FROM storage_duration d"
        + " JOIN lifetime_tech l USING (region, tech) ORDER BY d.tech, d.region"
    ).fetchall() == [
        ("AB", "E_BAT_2H-EXS", 2.0, 15.0),
        ("ON", "E_BAT_2H-NEW", 2.0, 15.0),
        ("ON", "E_PUMP_4H-EXS", 4.0, 100.0),
    ]
    # Existing battery: ATB (2022) fixed cost; pumped hydro: CODERS
    assert db.execute(
        "SELECT DISTINCT tech, cost FROM cost_fixed WHERE tech LIKE '%-EXS'"
        + " ORDER BY tech"
    ).fetchall() == [("E_BAT_2H-EXS", 25.0), ("E_PUMP_4H-EXS", 16.722)]
    assert db.execute(
        "SELECT vintage, cost FROM cost_invest ORDER BY vintage"
    ).fetchall() == [(2025, 900.0), (2030, 900.0), (2035, 900.0)]


def test_new_storage_needs_atb_costs():
    with pytest.raises(ValidationError, match="pump_4h"):
        StorageConfig(new_technologies=[PUMP4])

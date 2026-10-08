import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GenerationTechnology, GridLevel
from canoe.electricity.generation.entities import (
    ExistingGeneration,
    ExistingGenerationNotes,
    build_existing_generation,
)
from canoe.electricity.generation.parameters import (
    cogeneration_activity,
    existing_efficiencies,
    existing_om_costs,
)
from canoe.electricity.supply.entities import build_grid

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]
NOTES = ExistingGenerationNotes(
    capacity="capacity", atb_costs="atb", coders_costs="coders",
    atb_efficiency="atb", cogeneration="cogeneration",
)  # fmt: skip
CG = GenerationTechnology.NaturalGasCogeneration
MLY = GenerationTechnology.HydroMonthly
WIND = GenerationTechnology.WindOnshore
LIFETIMES = {CG: 30, MLY: 100, WIND: 30}


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the grid the generators inject into"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("ELCHR000",), ("ELCHRON000",), ("ELCHRQC000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, ?)",
        [
            (i, p, "e" if p < PERIODS[0] else "f")
            for i, p in enumerate([2000, 2020, 2024, *PERIODS])
        ],
    )
    build_grid(
        pd.DataFrame({"region": [ON, QC], "efficiency": [0.92, 0.92]}),
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


def _build(db: sqlite3.Connection) -> ExistingGeneration:
    # Ontario gas cogeneration (2000 retires in 2030) and wind; Quebec monthly hydro
    fleet = pd.DataFrame(
        {
            "region": [ON, ON, ON, QC],
            "technology": [CG, CG, WIND, MLY],
            "vintage": [2000, 2020, 2020, 2024],
            "capacity": [1.0, 0.5, 2.0, 24.0],
            "annual_energy": [20.0, 10.0, 18.0, 600.0],
            "facilities": ["A", "B", "C", "D"],
        }
    )
    generic = pd.DataFrame(
        {
            "efficiency": [0.47, None, None],
            "fixed_om": [17849.0, 19926.0, 38532.0],
            "variable_om": [2.73, 1.97, 0.0],
        },
        index=pd.Index(["ng_cg", "hydro_monthly", "wind_onshore"], name="coders_type"),
    )
    atb = pd.DataFrame(
        {
            "display_name": ["Land-Based Wind - Class 7 - Technology 1"],
            "parameter": ["Fixed O&M"],
            "year": [2022],
            "value": [30.0],
        }
    )
    generation = build_existing_generation(
        fleet,
        LIFETIMES,
        existing_efficiencies(fleet, generic, atb),
        existing_om_costs(fleet, generic, atb, LIFETIMES, PERIODS, 1.0, 1.0),
        cogeneration_activity(fleet, LIFETIMES, PERIODS, 0.95),
        NOTES,
        DATA_ID,
    )
    generation.build(db)
    return generation


def test_monthly_hydro_reservoir(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute(
        "SELECT tech, flag, reserve, seas_stor FROM technology "
        + "WHERE tech LIKE 'E_HYD_MLY%' ORDER BY tech"
    ).fetchall() == [("E_HYD_MLY-EXS", "ps", 1, 1), ("E_HYD_MLY-EXS-IN", "pb", 0, 0)]
    # Inflow fills the reservoir, the turbine empties it into the grid
    assert db.execute(
        "SELECT input_comm, tech, output_comm, efficiency FROM efficiency "
        + "WHERE tech LIKE 'E_HYD_MLY%' ORDER BY tech"
    ).fetchall() == [
        ("E_hyd_mly_stor", "E_HYD_MLY-EXS", "E_elc_tx", 1.0),
        ("E_ethos", "E_HYD_MLY-EXS-IN", "E_hyd_mly_stor", 1.0),
    ]
    assert db.execute(
        "SELECT e.tech, e.vintage, e.capacity, l.lifetime FROM existing_capacity e "
        + "JOIN lifetime_tech l USING (region, tech) "
        + "WHERE e.tech LIKE 'E_HYD_MLY%' ORDER BY e.tech"
    ).fetchall() == [
        ("E_HYD_MLY-EXS", 2024, 24.0, 100.0),
        ("E_HYD_MLY-EXS-IN", 2024, 24.0, 100.0),
    ]
    assert db.execute(
        "SELECT region, tech, duration FROM storage_duration"
    ).fetchall() == [("QC", "E_HYD_MLY-EXS", 730.0)]
    # Costs on the turbine only
    assert {
        row[0] for row in db.execute("SELECT tech FROM cost_fixed WHERE region = 'QC'")
    } == {"E_HYD_MLY-EXS"}


def test_cogeneration_held_at_historical_output(db: sqlite3.Connection):
    _ = _build(db)
    rows = db.execute(
        "SELECT period, operator, activity, units FROM limit_activity "
        + "WHERE tech_or_group = 'E_NG_CG-EXS' ORDER BY period, operator"
    ).fetchall()
    # Both vintages in 2025, only the 2020 one once the 2000 one retires (2030)
    assert [(p, o, round(a, 6), u) for p, o, a, u in rows] == [
        (2025, "ge", 28.5, "PJ"),
        (2025, "le", 30.0, "PJ"),
        (2030, "ge", 9.5, "PJ"),
        (2030, "le", 10.0, "PJ"),
        (2035, "ge", 9.5, "PJ"),
        (2035, "le", 10.0, "PJ"),
    ]


def test_fuels_and_sources(db: sqlite3.Connection):
    generation = _build(db)
    assert db.execute(
        "SELECT name, flag FROM commodity WHERE name IN ('E_ng', 'E_ethos') "
        + "ORDER BY name"
    ).fetchall() == [("E_ethos", "s"), ("E_ng", "a")]
    imports = declare_fuel_imports(CANOESector.Electricity, generation.technologies)
    assert [(i.fuel, i.provinces) for i in imports] == [(CANOEFuel.NaturalGas, (ON,))]
    assert db.execute(
        "SELECT tech, flag, reserve, curtail FROM technology "
        + "WHERE tech IN ('E_NG_CG-EXS', 'E_WND_ON-EXS') ORDER BY tech"
    ).fetchall() == [("E_NG_CG-EXS", "p", 1, 0), ("E_WND_ON-EXS", "p", 1, 1)]
    # Wind: ATB fixed cost, no variable cost (zero), free input
    assert db.execute(
        "SELECT DISTINCT cost FROM cost_fixed WHERE tech = 'E_WND_ON-EXS'"
    ).fetchall() == [(30.0,)]
    assert (
        db.execute(
            "SELECT COUNT(*) FROM cost_variable WHERE tech = 'E_WND_ON-EXS'"
        ).fetchone()[0]
        == 0
    )

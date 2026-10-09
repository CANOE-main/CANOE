import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.canoe_objects.fuel_imports import declare_fuel_imports
from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GenerationTechnology, GridLevel
from canoe.electricity.generation.entities import (
    CarbonCapture,
    GenerationEntities,
    GenerationNotes,
    build_existing_generation,
    build_new_generation,
    build_vre_bins,
)
from canoe.electricity.generation.parameters import (
    cogeneration_activity,
    existing_processes,
    new_processes,
    process_efficiencies,
    process_investment_costs,
    process_om_costs,
    vre_bin_capacity_factors,
    vre_bin_costs,
    vre_bin_limits,
)
from canoe.electricity.supply.entities import build_grid

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]
NOTES = GenerationNotes(
    capacity="capacity", atb_costs="atb", coders_costs="coders",
    atb_efficiency="atb", cogeneration="cogeneration", vre_bin_costs="bins",
    vre_bin_limits="limits", vre_bin_capacity_factors="bin profiles",
    vre_capacity_factors="vre", hydro_capacity_factors="hydro", capture="capture",
)  # fmt: skip
HOURS = 8760
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
    db.executemany(
        "INSERT INTO time_season (sequence, season, segment_fraction) VALUES (?, ?, ?)",
        [(d, f"D{d + 1:03d}", 1 / 365) for d in range(365)],
    )
    db.executemany(
        "INSERT INTO time_of_day (sequence, tod, hours) VALUES (?, ?, 1)",
        [(h, f"H{h + 1:02d}") for h in range(24)],
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


def _build(db: sqlite3.Connection) -> GenerationEntities:
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
    processes = existing_processes(fleet)
    generation = build_existing_generation(
        fleet,
        LIFETIMES,
        process_efficiencies(processes, generic, atb),
        process_om_costs(processes, generic, atb, LIFETIMES, PERIODS, 1.0, 1.0),
        cogeneration_activity(fleet, LIFETIMES, PERIODS, 0.95),
        # Ontario wind: 0.3 by day (hours 8-19), 0 at night
        pd.DataFrame(
            {
                "region": ON,
                "technology": WIND,
                "hour": range(HOURS),
                "factor": [0.3 if 8 <= h % 24 < 20 else 0.0 for h in range(HOURS)],
            }
        ),
        # Quebec monthly hydro: 0.5 every day
        pd.DataFrame(
            {"region": QC, "technology": MLY, "day": range(365), "factor": 0.5}
        ),
        CarbonCapture(),
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
    # The daily limits of monthly hydro are on its inflow
    assert db.execute(
        "SELECT tech_or_group, operator, COUNT(*), MIN(factor), MAX(factor)"
        + " FROM limit_seasonal_capacity_factor GROUP BY tech_or_group"
    ).fetchall() == [("E_HYD_MLY-EXS-IN", "le", 365, 0.5, 0.5)]
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
    # Wind: hourly capacity factors, 8760 time slices
    assert db.execute(
        "SELECT COUNT(*), SUM(factor > 0) FROM capacity_factor_tech"
        + " WHERE tech = 'E_WND_ON-EXS' AND region = 'ON'"
    ).fetchone() == (HOURS, 365 * 12)
    assert db.execute(
        "SELECT season, tod, factor FROM capacity_factor_tech"
        + " WHERE tod IN ('H08', 'H09') AND season = 'D002' ORDER BY tod"
    ).fetchall() == [("D002", "H08", 0.0), ("D002", "H09", 0.3)]
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


def test_new_generation_reads_atb_at_projection_year(db: sqlite3.Connection):
    SMR = GenerationTechnology.NuclearSMR
    # Period end: 2025 -> 2030, 2030 -> 2035, 2035 -> 2040
    processes = new_processes([SMR], [ON], {2025: 2030, 2030: 2035, 2035: 2040})
    atb = pd.DataFrame(
        [
            ("Nuclear - Small", parameter, year, value + year - 2030)
            for parameter, value in (
                ("Heat Rate", 10.0),
                ("OCC", 9000.0),
                ("Fixed O&M", 150.0),
                ("Variable O&M", 3.6),
            )
            for year in (2030, 2035, 2040)
        ],
        columns=["display_name", "parameter", "year", "value"],
    )
    generation = build_new_generation(
        process_efficiencies(processes, pd.DataFrame(), atb),
        process_investment_costs(processes, atb, 2.0),
        process_om_costs(processes, pd.DataFrame(), atb, {SMR: 60}, PERIODS, 2.0, 1.0),
        {SMR: 60},
        CarbonCapture(),
        NOTES,
        DATA_ID,
    )
    generation.build(db)
    assert db.execute(
        "SELECT tech, flag, reserve FROM technology WHERE tech = 'E_NUC_SMR-NEW'"
    ).fetchall() == [("E_NUC_SMR-NEW", "pb", 1)]
    assert db.execute(
        "SELECT vintage, cost, units FROM cost_invest ORDER BY vintage"
    ).fetchall() == [
        (2025, 18000.0, "M$/GW"),
        (2030, 18010.0, "M$/GW"),
        (2035, 18020.0, "M$/GW"),
    ]
    # Fixed cost of a vintage is constant over the periods it lives
    assert db.execute(
        "SELECT vintage, period, cost FROM cost_fixed ORDER BY vintage, period"
    ).fetchall() == [
        (2025, 2025, 300.0),
        (2025, 2030, 300.0),
        (2025, 2035, 300.0),
        (2030, 2030, 310.0),
        (2030, 2035, 310.0),
        (2035, 2035, 320.0),
    ]
    assert db.execute(
        "SELECT DISTINCT input_comm, output_comm FROM efficiency"
        + " WHERE tech = 'E_NUC_SMR-NEW'"
    ).fetchall() == [("E_eur", "E_elc_tx")]
    imports = declare_fuel_imports(CANOESector.Electricity, generation.technologies)
    assert [(i.fuel, i.provinces) for i in imports] == [
        (CANOEFuel.EnrichedUranium, (ON,))
    ]


def test_vre_bins(db: sqlite3.Connection):
    costs = pd.DataFrame(
        [
            (region, WIND, number, vintage, 1000.0 * number)
            for region in (ON, QC)
            for number in (1, 2)
            for vintage in PERIODS
        ],
        columns=["region", "technology", "bin", "vintage", "cost"],
    )
    limits = pd.DataFrame(
        [
            (region, WIND, number, period, 0.5)
            for region in (ON, QC)
            for number in (1, 2)
            for period in PERIODS
        ],
        columns=["region", "technology", "bin", "period", "capacity"],
    )
    investment, fixed = vre_bin_costs(
        costs, costs.assign(cost=30.0), [WIND], [ON], PERIODS, LIFETIMES, 0.5
    )
    # Hourly profile of each bin and vintage: the vintage's share of 0.1 per bin
    factors = pd.DataFrame(
        [
            (region, WIND, number, vintage, hour, 0.1 * number + (vintage - 2025) / 100)
            for region in (ON, QC)
            for number in (1, 2)
            for vintage in PERIODS
            for hour in range(HOURS)
        ],
        columns=["region", "technology", "bin", "vintage", "hour", "factor"],
    )
    generation = build_vre_bins(
        investment,
        fixed,
        vre_bin_limits(limits, [WIND], [ON], PERIODS),
        vre_bin_capacity_factors(factors, [WIND], [ON], PERIODS, 0.01),
        LIFETIMES,
        NOTES,
        DATA_ID,
    )
    generation.build(db)
    assert db.execute(
        "SELECT tech, reserve, curtail FROM technology ORDER BY tech"
    ).fetchall()[-2:] == [("E_WND_ON-NEW-1", 1, 1), ("E_WND_ON-NEW-2", 1, 1)]
    # Only the modelled province, costs converted
    assert db.execute(
        "SELECT DISTINCT region, tech, cost FROM cost_invest ORDER BY tech"
    ).fetchall() == [("ON", "E_WND_ON-NEW-1", 500.0), ("ON", "E_WND_ON-NEW-2", 1000.0)]
    assert db.execute(
        "SELECT region, period, operator, capacity, units FROM limit_capacity"
        + " WHERE tech_or_group = 'E_WND_ON-NEW-1' ORDER BY period"
    ).fetchall() == [("ON", p, "le", 0.5, "GW") for p in PERIODS]
    assert db.execute(
        "SELECT COUNT(*), MIN(cost), MAX(cost) FROM cost_fixed"
        + " WHERE tech = 'E_WND_ON-NEW-1'"
    ).fetchone() == (6, 15.0, 15.0)
    assert db.execute(
        "SELECT DISTINCT input_comm, efficiency FROM efficiency"
        + " WHERE tech LIKE 'E_WND_ON-NEW-%'"
    ).fetchall() == [("E_ethos", 1.0)]
    # Capacity factors by vintage, only the modelled province
    assert db.execute(
        "SELECT region, tech, vintage, COUNT(*), MIN(factor), MAX(factor)"
        + " FROM capacity_factor_process GROUP BY region, tech, vintage"
        + " ORDER BY tech, vintage"
    ).fetchall() == [
        ("ON", f"E_WND_ON-NEW-{n}", v, HOURS, f, f)
        for n in (1, 2)
        for v, f in zip(PERIODS, (0.1 * n, 0.1 * n + 0.05, 0.1 * n + 0.1))
    ]

import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema
from pydantic import ValidationError

from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import CCSRetrofit, GenerationTechnology, GridLevel
from canoe.electricity.config import GenerationConfig
from canoe.electricity.generation.ccs import (
    generator_capture_factors,
    retrofit_capture_factors,
    retrofit_efficiencies,
    retrofit_om_costs,
    retrofit_processes,
)
from canoe.electricity.generation.entities import (
    CarbonCapture,
    GenerationNotes,
    build_ccs_retrofits,
    build_new_generation,
    retrofit_intermediate_commodity,
)
from canoe.electricity.generation.parameters import (
    new_processes,
    process_efficiencies,
    process_investment_costs,
    process_om_costs,
)
from canoe.electricity.supply.entities import build_grid

ON = CANOEProvince.ONTARIO
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]
YEARS = {2025: 2030, 2030: 2035, 2035: 2040}
NOTES = GenerationNotes(
    capacity="capacity", atb_costs="atb", coders_costs="coders",
    atb_efficiency="atb", cogeneration="cogeneration", vre_bin_costs="bins",
    vre_bin_limits="limits", vre_bin_capacity_factors="bin profiles",
    vre_capacity_factors="vre", hydro_capacity_factors="hydro", capture="capture",
    capacity_credits="credits", reserve_derates="derates",
    vre_bin_capacity_credits="bin credits", ramp_rates="ramps",
)  # fmt: skip
COAL, NG_CCS = GenerationTechnology.Coal, GenerationTechnology.NaturalGasCCS
CO2 = {CANOEFuel.Coal: 86.02, CANOEFuel.NaturalGas: 51.88}


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the grid"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)", [("ELCHR000",), ("ELCHRON000",)]
    )
    db.execute("INSERT INTO region (region) VALUES ('ON')")
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        list(enumerate(PERIODS)),
    )
    # Registered by the central emissions step and by the fuel commodities
    for name, flag in (("co2", "e"), ("E_ng", "a")):
        db.execute("INSERT INTO commodity_label (commodity) VALUES (?)", (name,))
        db.execute("INSERT INTO commodity (name, flag) VALUES (?, ?)", (name, flag))
    build_grid(
        pd.DataFrame({"region": [ON], "efficiency": [0.92]}),
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


def test_retrofit_where_generators_live():
    # Ontario coal of vintages 1990 and 2000, 45-year life: the last retires in 2045
    fleet = pd.DataFrame(
        {"region": [ON, ON], "technology": [COAL, COAL], "vintage": [1990, 2000]}
    )
    processes, bypasses = retrofit_processes(
        fleet, [CCSRetrofit.Coal90], [], [ON], YEARS, {COAL: 45}
    )
    assert processes[["vintage", "atb_year", "lifetime"]].values.tolist() == [
        [2025, 2030, 20],
        [2030, 2035, 15],
        [2035, 2040, 10],
    ]
    assert bypasses["lifetime"].tolist() == [20]


def test_retrofit_chain_and_capture(db: sqlite3.Connection):
    retrofits = [CCSRetrofit.Coal90]
    fleet = pd.DataFrame({"region": [ON], "technology": [COAL], "vintage": [2000]})
    processes, bypasses = retrofit_processes(
        fleet, retrofits, [], [ON], YEARS, {COAL: 45}
    )
    atb = pd.DataFrame(
        [
            ("Coal integrated retrofit 90%-CCS", parameter, year, value)
            for parameter, value in (
                ("Net Output Penalty", -0.2),
                ("Additional OCC", 1000.0),
                ("Fixed O&M", 50.0),
            )
            for year in YEARS.values()
        ],
        columns=["display_name", "parameter", "year", "value"],
    )
    captures = retrofit_capture_factors(retrofits, CO2, {COAL: 8.49})
    build_ccs_retrofits(
        processes,
        bypasses,
        retrofit_efficiencies(processes, atb),
        process_investment_costs(processes, atb, 1.0, metric="Additional OCC"),
        retrofit_om_costs(processes, atb, PERIODS, 1.0),
        captures,
        NOTES,
        DATA_ID,
    ).build(db)

    intermediate = retrofit_intermediate_commodity(COAL)
    assert db.execute(
        "SELECT name, flag FROM commodity WHERE name = ?", (intermediate,)
    ).fetchall() == [("E_elc_tx_coal", "p")]
    assert db.execute(
        "SELECT tech, unlim_cap, reserve FROM technology WHERE tech LIKE 'E_COAL%'"
        + " ORDER BY tech"
    ).fetchall() == [("E_COAL_CCS_RFIT_90", 0, 0), ("E_COAL_RFIT_BYPASS", 1, 0)]
    assert db.execute(
        "SELECT DISTINCT tech, input_comm, output_comm, efficiency FROM efficiency"
        + " WHERE input_comm = 'E_elc_tx_coal' ORDER BY tech"
    ).fetchall() == [
        ("E_COAL_CCS_RFIT_90", "E_elc_tx_coal", "E_elc_tx", 0.8),
        ("E_COAL_RFIT_BYPASS", "E_elc_tx_coal", "E_elc_tx", 1.0),
    ]
    # Captured per unit of retrofit output: 0.9 × 86.02 × 8.49 × 0.29307 / 0.8
    rows = db.execute(
        "SELECT vintage, emis_comm, activity, units FROM emission_activity ORDER BY vintage"
    ).fetchall()
    expected = -0.9 * 86.02 * 8.49 * 0.29307107 / 0.8
    assert [(v, e, round(a, 6), u) for v, e, a, u in rows] == [
        (v, "co2", round(expected, 6), "kt/PJ") for v in PERIODS
    ]
    assert db.execute(
        "SELECT vintage, lifetime FROM lifetime_process ORDER BY vintage"
    ).fetchall() == [(2025, 20.0), (2030, 15.0), (2035, 10.0)]
    assert db.execute(
        "SELECT DISTINCT cost FROM cost_invest WHERE tech = 'E_COAL_CCS_RFIT_90'"
    ).fetchall() == [(1000.0,)]


def test_generators_built_with_capture(db: sqlite3.Connection):
    processes = new_processes([NG_CCS], [ON], YEARS)
    atb = pd.DataFrame(
        [
            ("NG 2-on-1 Combined Cycle (H-Frame) 95% CCS", parameter, year, value)
            for parameter, value in (("Heat Rate", 7.0), ("OCC", 2000.0))
            for year in YEARS.values()
        ],
        columns=["display_name", "parameter", "year", "value"],
    )
    efficiencies = process_efficiencies(processes, pd.DataFrame(), atb)
    build_new_generation(
        efficiencies,
        process_investment_costs(processes, atb, 1.0),
        process_om_costs(
            processes, pd.DataFrame(), atb, {NG_CCS: 45}, PERIODS, 1.0, 1.0
        ),
        {NG_CCS: 45},
        CarbonCapture(factors=generator_capture_factors([NG_CCS], CO2)),
        NOTES,
        DATA_ID,
    ).build(db)
    # 95% of the gas's CO2 per unit of fuel, divided by the efficiency per output
    efficiency = float(efficiencies["efficiency"].iloc[0])
    (activity,) = db.execute(
        "SELECT DISTINCT activity FROM emission_activity WHERE tech = 'E_NG_CCS-NEW'"
    ).fetchone()
    assert activity == pytest.approx(-0.95 * 51.88 / efficiency)


def test_retrofits_need_a_heat_rate():
    with pytest.raises(ValidationError, match="ccs_retrofit_heat_rates"):
        GenerationConfig(
            new_technologies=[],
            ccs_retrofits=[CCSRetrofit.Coal90],
            ccs_retrofit_heat_rates={GenerationTechnology.NaturalGasCC: 6.2},
        )

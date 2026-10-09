import sqlite3

import numpy as np
import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.canoe_objects.array_types import (
    RegionalValuesArray,
    RegionVintageArray,
    RegionVintagePeriodArray,
)
from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GenerationTechnology, GridLevel
from canoe.electricity.generation.entities import (
    CarbonCapture,
    GenerationNotes,
    Reliability,
    build_existing_generation,
)
from canoe.electricity.generation.parameters import (
    existing_processes,
    process_efficiencies,
    process_om_costs,
)
from canoe.electricity.loaders import (
    get_coders_reserve_margins,
    get_ieso_summer_peak_capability,
    get_ramp_rates,
)
from canoe.electricity.reliability import (
    ieso_capacity_ratios,
    planning_reserve_margins,
    process_capacity_credits,
    process_reserve_derates,
    vre_bin_capacity_credits,
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
    capacity_credits="credits", reserve_derates="derates",
    vre_bin_capacity_credits="bin credits", ramp_rates="ramps",
)  # fmt: skip
HOURS, DAYS = 8760, 365
CC = GenerationTechnology.NaturalGasCC
MLY = GenerationTechnology.HydroMonthly
WIND = GenerationTechnology.WindOnshore
LIFETIMES = {CC: 30, MLY: 100, WIND: 30}


def _grid(margins: pd.DataFrame | None = None) -> sqlite3.Connection:
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
        [(d, f"D{d + 1:03d}", 1 / DAYS) for d in range(DAYS)],
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
        reserve_margins=margins,
    ).build(db)
    return db


def _build(db: sqlite3.Connection, reliability: Reliability | None, reproduce: bool):
    # Ontario gas combined cycle (2000 retires in 2030) and wind; Quebec monthly hydro
    fleet = pd.DataFrame(
        {
            "region": [ON, ON, ON, QC],
            "technology": [CC, CC, WIND, MLY],
            "vintage": [2000, 2020, 2020, 2024],
            "capacity": [1.0, 0.5, 2.0, 24.0],
            "annual_energy": [5.0, 3.0, 18.0, 600.0],
            "facilities": ["A", "B", "C", "D"],
        }
    )
    generic = pd.DataFrame(
        {
            "efficiency": [0.5, None, None],
            "fixed_om": [10000.0, 19926.0, 38532.0],
            "variable_om": [2.0, 1.97, 0.0],
        },
        index=pd.Index(["ng_cc", "hydro_monthly", "wind_onshore"], name="coders_type"),
    )
    atb = pd.DataFrame(
        {
            "display_name": [
                "Land-Based Wind - Class 7 - Technology 1",
                "NG 2-on-1 Combined Cycle (H-Frame)",
                "NG 2-on-1 Combined Cycle (H-Frame)",
            ],
            "parameter": ["Fixed O&M", "Heat Rate", "Fixed O&M"],
            "year": [2022] * 3,
            "value": [30.0, 6.2, 20.0],
        }
    )
    processes = existing_processes(fleet)
    if reliability is None:
        ratios = ieso_capacity_ratios(get_ieso_summer_peak_capability(2025), "Firm")
        reliability = Reliability(
            credits=process_capacity_credits(processes, ratios, LIFETIMES, PERIODS),
            derates=process_reserve_derates(processes, ratios, reproduce),
            ramp_rates=get_ramp_rates(),
        )
    build_existing_generation(
        fleet,
        LIFETIMES,
        process_efficiencies(processes, generic, atb),
        process_om_costs(processes, generic, atb, LIFETIMES, PERIODS, 1.0, 1.0),
        pd.DataFrame(columns=["region", "technology", "period"]),
        pd.DataFrame(
            {"region": ON, "technology": WIND, "hour": range(HOURS), "factor": 0.3}
        ),
        pd.DataFrame(
            {"region": QC, "technology": MLY, "day": range(DAYS), "factor": 0.5}
        ),
        CarbonCapture(),
        NOTES,
        DATA_ID,
        reliability,
    ).build(db)


def test_ieso_ratios():
    ratios = ieso_capacity_ratios(get_ieso_summer_peak_capability(2025), "Firm")
    # The reference database's values
    assert ratios[GenerationTechnology.Coal] == pytest.approx(0.85785315649252469)
    assert ratios[GenerationTechnology.HydroDaily] == pytest.approx(0.59722473270781551)
    assert ratios[GenerationTechnology.NuclearSMR] == pytest.approx(0.7838019730470609)
    assert ratios[GenerationTechnology.Biogas] == pytest.approx(0.88842398884239893)
    assert ratios[GenerationTechnology.SolarPV] == pytest.approx(0.13775207095640532)
    assert ratios[WIND] == pytest.approx(0.14879265831137772)
    assert GenerationTechnology.Geothermal not in ratios


def test_stand_in_year():
    with pytest.raises(ValueError, match="only 2025"):
        get_ieso_summer_peak_capability(2024)


def test_capacity_credits_while_alive():
    db = _grid()
    _build(db, None, reproduce=False)
    rows = db.execute(
        "SELECT region, tech, vintage, period, round(credit, 4) FROM capacity_credit "
        + "ORDER BY tech, vintage, period"
    ).fetchall()
    assert rows == [
        *[("QC", "E_HYD_MLY-EXS", 2024, p, 0.5972) for p in PERIODS],
        # 2000 combined cycle retires in 2030
        ("ON", "E_NG_CC-EXS", 2000, 2025, 0.8579),
        *[("ON", "E_NG_CC-EXS", 2020, p, 0.8579) for p in PERIODS],
        *[("ON", "E_WND_ON-EXS", 2020, p, 0.1488) for p in PERIODS],
    ]


@pytest.mark.parametrize("reproduce", [False, True])
def test_derates(reproduce: bool):
    db = _grid()
    _build(db, None, reproduce=reproduce)
    rows = db.execute(
        "SELECT tech, vintage, count(*), round(min(factor), 4), round(max(factor), 4) "
        + "FROM reserve_capacity_derate GROUP BY tech, vintage ORDER BY tech, vintage"
    ).fetchall()
    # Wind: its capacity factor is its availability. Monthly hydro: its discharge,
    # already limited by the water stored, unless the previous derate is reproduced
    expected = [
        ("E_NG_CC-EXS", 2000, DAYS, 0.8579, 0.8579),
        ("E_NG_CC-EXS", 2020, DAYS, 0.8579, 0.8579),
    ]
    if reproduce:
        expected.insert(0, ("E_HYD_MLY-EXS", 2024, DAYS, 0.5972, 0.5972))
    assert rows == expected


def test_ramp_rates():
    db = _grid()
    _build(db, None, reproduce=False)
    for table in ("ramp_up_hourly", "ramp_down_hourly"):
        assert db.execute(f"SELECT region, tech, rate FROM {table}").fetchall() == [
            ("ON", "E_NG_CC-EXS", 0.25)
        ]


def test_no_reliability_writes_nothing():
    db = _grid()
    _build(db, Reliability(), reproduce=False)
    for table in (
        "capacity_credit",
        "reserve_capacity_derate",
        "ramp_up_hourly",
        "planning_reserve_margin",
    ):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_planning_reserve_margins():
    db = _grid(planning_reserve_margins(get_coders_reserve_margins(), [ON, QC]))
    assert db.execute(
        "SELECT region, margin, data_id FROM planning_reserve_margin ORDER BY region"
    ).fetchall() == [("ON", 0.19, "ELCHRON000"), ("QC", 0.095, "ELCHRQC000")]


def test_planning_reserve_margin_missing():
    margins = pd.DataFrame({"region": [ON], "margin": [0.19]})
    with pytest.raises(ValueError, match="No planning reserve margin"):
        planning_reserve_margins(margins, [ON, QC])


def test_vre_bin_credits_need_every_vintage():
    credits = pd.DataFrame(
        {
            "region": ON,
            "technology": WIND,
            "bin": 1,
            "vintage": [2025, 2025, 2030],
            "period": [2025, 2030, 2030],
            "credit": 0.4,
        }
    )
    assert len(vre_bin_capacity_credits(credits, [WIND], [ON], [2025, 2030])) == 3
    with pytest.raises(ValueError, match="without a capacity credit"):
        vre_bin_capacity_credits(credits, [WIND], [ON], PERIODS)


class TestValidation:
    def _entity(self) -> TechnologyEntity:
        return TechnologyEntity("E_TEST", "E_elc_tx", DATA_ID).with_efficiency(
            "E_ethos", RegionVintageArray([ON], [2025], fill=1.0)
        )

    def test_credit_needs_reserve(self):
        entity = self._entity().with_capacity_credit(
            RegionVintagePeriodArray([ON], [2025], [2025], fill=0.5)
        )
        with pytest.raises(ValueError, match="not in the reserve"):
            entity.validate()

    def test_credit_within_life(self):
        entity = (
            self._entity()
            .set_reserve()
            .with_lifetime(RegionalValuesArray([ON], fill=5))
            .with_capacity_credit(
                RegionVintagePeriodArray([ON], [2025], [2025, 2030], fill=0.5)
            )
        )
        with pytest.raises(ValueError, match="after the end of life"):
            entity.validate()

    def test_ramp_rate_positive(self):
        rates = RegionalValuesArray([ON], fill=0.0)
        entity = self._entity().with_ramp_rates(rates, rates)
        with pytest.raises(ValueError, match=r"outside \(0, 1\]"):
            entity.validate()

    def test_credit_at_most_one(self):
        values = np.full((1, 1, 1), 1.5)
        credits = RegionVintagePeriodArray([ON], [2025], [2025])
        credits.data[:] = values
        entity = self._entity().set_reserve().with_capacity_credit(credits)
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            entity.validate()

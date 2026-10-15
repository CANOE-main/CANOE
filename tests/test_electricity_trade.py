import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.canoe_objects.array_types import PairValuesArray
from canoe.canoe_objects.exchange import ExchangeTechnologyEntity
from canoe.common import CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.electricity.catalogue import GridLevel
from canoe.electricity.loaders import (
    get_coders_provincial_demand,
    get_coders_transfers,
)
from canoe.electricity.supply.entities import build_exogenous_demand, build_grid
from canoe.electricity.supply.parameters import (
    exogenous_demand_profiles,
    exogenous_demands,
)
from canoe.electricity.trade.entities import (
    TradeNotes,
    build_boundary,
    build_interties,
)
from canoe.electricity.trade.parameters import (
    boundary_flows,
    endogenous_interties,
    export_demands,
    export_profiles,
    import_capacities,
    import_capacity_factors,
    intertie_capacities,
    intertie_capacity_factors,
)

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
DATA_ID = DatasetIdentifier(CANOESector.Electricity, "HR", "000")
PERIODS = [2025, 2030, 2035]
HOURS = 8760
NOTES = TradeNotes(losses="losses", capacities="ttc", flows="flows", costs="costs")
COSTS = pd.DataFrame(
    [(level, p, 2.0) for level in GridLevel for p in PERIODS],
    columns=["level", "period", "cost"],
)


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the grid the interties connect"""
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
            for i, p in enumerate([2024, *PERIODS])
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
        COSTS,
        [],
        first_period=2025,
        lifetime=15,
        cost_notes="test",
        data_id=DATA_ID,
    ).build(db)
    return db


def _interfaces() -> pd.DataFrame:
    # Ontario-Quebec: two interties, seasonal one way; Ontario-US (boundary)
    return pd.DataFrame(
        {
            "from_region": ["ON", "ON", "QC", "QC", "ON"],
            "to_region": ["QC", "QC", "ON", "ON", "USA"],
            "ttc_summer": [95.0, 470.0, 65.0, 800.0, 1700.0],
            "ttc_winter": [110.0, 470.0, 85.0, 800.0, 1750.0],
            "interties": ["Kipawa", "Beauharnois", "Kipawa", "Beauharnois", "St Clair"],
        }
    )


def test_transfers_sign():
    # Negative transfers leave the province: Quebec and Ontario export to the US
    transfers = get_coders_transfers(2018)
    flows = boundary_flows(transfers, list(CANOEProvince))

    def twh(region: CANOEProvince, column: str) -> float:
        return float(flows.loc[flows["region"] == region, column].sum()) / 1e6

    assert twh(QC, "outflow") == pytest.approx(24.5, abs=0.1)
    assert twh(ON, "outflow") == pytest.approx(15.5, abs=0.1)
    assert twh(QC, "inflow") < 0.1


def test_stand_in_years():
    with pytest.raises(ValueError, match="only 2018"):
        get_coders_transfers(2019)
    with pytest.raises(ValueError, match="only 2018"):
        get_coders_provincial_demand(2022)


def test_boundary_of_left_out_province():
    # Quebec left out: Ontario's transfers with it are boundary flows
    flows = boundary_flows(get_coders_transfers(2018), [ON])
    assert sorted(set(flows["outside"])) == ["MB", "QC", "USA"]
    assert (flows["region"] == ON).all()


def test_interties(db: sqlite3.Connection):
    interties = endogenous_interties(_interfaces(), [ON, QC])
    capacities = intertie_capacities(interties)
    build_interties(
        interties,
        capacities,
        intertie_capacity_factors(interties, capacities, 0.01),
        {ON: 0.025, QC: 0.053},
        COSTS,
        2024,
        26,
        NOTES,
        DATA_ID,
    ).build(db)
    assert db.execute(
        "SELECT region, efficiency FROM efficiency WHERE tech = 'E_INT' ORDER BY region"
    ).fetchall() == [("ON-QC", 0.975), ("QC-ON", 0.947)]
    # One capacity both ways: the largest capability (Quebec to Ontario in winter,
    # 85 + 800 MW)
    assert db.execute(
        "SELECT region, capacity, vintage FROM existing_capacity ORDER BY region"
    ).fetchall() == [("ON-QC", 0.885, 2024), ("QC-ON", 0.885, 2024)]
    rows = db.execute(
        "SELECT region, round(factor, 4), count(*) FROM capacity_factor_tech "
        + "GROUP BY region, round(factor, 4) ORDER BY region, 2"
    ).fetchall()
    # Summer (May-October, 4416 hours) and winter capability over 885 MW
    assert rows == [
        ("ON-QC", round(565 / 885, 4), 4416),
        ("ON-QC", round(580 / 885, 4), 4344),
        ("QC-ON", round(865 / 885, 4), 4416),
        ("QC-ON", 1.0, 4344),
    ]
    assert db.execute(
        "SELECT count(*), min(lifetime) FROM lifetime_tech WHERE tech = 'E_INT'"
    ).fetchone() == (2, 26.0)
    assert db.execute(
        "SELECT count(*) FROM cost_variable WHERE tech = 'E_INT'"
    ).fetchone() == (2 * len(PERIODS),)


def test_no_capacity_factors_when_constant():
    interfaces = _interfaces().assign(ttc_summer=100.0, ttc_winter=100.0)
    interties = endogenous_interties(interfaces, [ON, QC])
    factors = intertie_capacity_factors(interties, intertie_capacities(interties), 0.01)
    assert factors.empty


def test_missing_reverse_direction():
    interfaces = _interfaces().iloc[[0, 1, 4]]
    with pytest.raises(ValueError, match="no reverse direction"):
        endogenous_interties(interfaces, [ON, QC])


def test_exchange_needs_equal_capacities():
    pairs = [(ON, QC), (QC, ON)]
    capacity = PairValuesArray(pairs, fill=1.0)
    capacity.set(2.0, pair=(QC, ON))
    entity = (
        ExchangeTechnologyEntity("E_INT", "E_elc_tx", 2024, DATA_ID)
        .with_efficiency(PairValuesArray(pairs, fill=1.0))
        .with_existing_capacity(capacity)
    )
    with pytest.raises(ValueError, match="must be equal"):
        entity.validate()


def test_boundary(db: sqlite3.Connection):
    # Ontario: 100 MWh out in hour 0, 20 MWh in in hour 1, nothing otherwise
    transfers = pd.DataFrame(
        {
            "region_1": "ON",
            "region_2": "USA",
            "hour": range(HOURS),
            "transfer": [-100.0, 20.0] + [0.0] * (HOURS - 2),
        }
    )
    flows = boundary_flows(transfers, [ON, QC])
    build_boundary(
        export_demands(flows, PERIODS),
        export_profiles(flows),
        import_capacities(flows),
        import_capacity_factors(flows, 0.01),
        {ON: 0.025, QC: 0.053},
        COSTS,
        2024,
        26,
        NOTES,
        DATA_ID,
    ).build(db)
    assert db.execute(
        "SELECT tech, annual, unlim_cap, curtail FROM technology "
        + "WHERE tech LIKE 'E_INT%' ORDER BY tech"
    ).fetchall() == [("E_INT_IN-USA", 0, 0, 1), ("E_INT_OUT-USA", 1, 1, 0)]
    assert db.execute(
        "SELECT region, period, round(demand, 8) FROM demand ORDER BY period"
    ).fetchall() == [("ON", p, 0.00036) for p in PERIODS]
    assert db.execute(
        "SELECT season, tod, dsd FROM demand_specific_distribution "
        + "WHERE period = 2025 AND dsd > 0"
    ).fetchall() == [("D001", "H01", 1.0)]
    assert db.execute(
        "SELECT input_comm, output_comm, efficiency FROM efficiency "
        + "WHERE tech = 'E_INT_OUT-USA'"
    ).fetchall() == [("E_elc_tx", "E_D_elc_int_usa", 0.975)]
    assert db.execute(
        "SELECT capacity FROM existing_capacity WHERE tech = 'E_INT_IN-USA'"
    ).fetchall() == [(0.02,)]
    assert db.execute(
        "SELECT season, tod, factor FROM capacity_factor_tech "
        + "WHERE tech = 'E_INT_IN-USA' AND factor > 0"
    ).fetchall() == [("D001", "H02", 1.0)]


def test_exogenous_demand(db: sqlite3.Connection):
    annual = pd.DataFrame(
        {"region": ON, "year": [2030, 2035, 2040], "demand": [1e5, 1.1e5, 1.2e5]}
    )
    hourly = pd.DataFrame({"region": ON, "hour": range(HOURS), "demand": 1.0})
    demand, technology = build_exogenous_demand(
        exogenous_demands(annual, [ON], {2025: 2030, 2030: 2035, 2035: 2040}),
        exogenous_demand_profiles(hourly, [ON], 0.02),
        2025,
        25,
        "CODERS",
        DATA_ID,
    )
    demand.build(db)
    technology.build(db)
    assert db.execute(
        "SELECT period, round(demand, 6) FROM demand WHERE commodity = 'E_D_elc'"
    ).fetchall() == [(2025, 360.0), (2030, 396.0), (2035, 432.0)]
    assert db.execute(
        "SELECT round(sum(dsd), 9) FROM demand_specific_distribution WHERE period = 2025"
    ).fetchone() == (1.0,)
    assert db.execute(
        "SELECT input_comm, output_comm FROM efficiency WHERE tech = 'E_ELC_DEM'"
    ).fetchall() == [("E_elc_dem", "E_D_elc")]

import sqlite3

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema

from canoe.common import (
    CANOEEmission,
    CANOEEmissionDeclaration,
    CANOEFuel,
    CANOEProvince,
    CANOESector,
)
from canoe.common.naming import DatasetIdentifier
from canoe.fuel.entities import build_fuel_supply

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
NG = CANOEFuel.NaturalGas
DATA_ID = DatasetIdentifier(CANOESector.Fuel, "HR", "000")


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the rows the sectors and the emissions step would write"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("FUELHR000",), ("FUELHRON000",), ("FUELHRQC000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        [(0, 2025), (1, 2030), (2, 2035)],
    )
    db.executemany(
        "INSERT INTO commodity_label (commodity) VALUES (?)",
        [("C_ng",), ("A_ng",), ("co2",), ("ch4",), ("n2o",)],
    )
    return db


def _costs(rows: list[tuple[object, ...]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[*columns, "cost", "notes"])


def _import_costs() -> pd.DataFrame:
    return _costs(
        [
            (ON, 2025, NG, 3.9, "Lowest delivered price: electric power"),
            (ON, 2030, NG, 4.2, "Lowest delivered price: electric power"),
            (QC, 2025, NG, 3.9, "Lowest delivered price: electric power"),
        ],
        ["region", "period", "fuel"],
    )


def _distribution_costs() -> pd.DataFrame:
    return _costs(
        [
            (
                ON,
                2025,
                CANOESector.Commercial,
                NG,
                6.2,
                "Commercial price minus import",
            ),
            (
                ON,
                2030,
                CANOESector.Commercial,
                NG,
                6.5,
                "Commercial price minus import",
            ),
            (
                ON,
                2025,
                CANOESector.Agriculture,
                NG,
                0.4,
                "Industrial price minus import",
            ),
        ],
        ["region", "period", "sector", "fuel"],
    )


def _upstream_factors() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fuel": [NG],
            "emission": [CANOEEmission.CO2],
            "factor": [10.26],
            "notes": ["Upstream emissions"],
            "reference": ["ECCC Fuel LCA"],
        }
    )


def _combustion_factors() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector": [CANOESector.Commercial, CANOESector.Commercial],
            "fuel": [NG, NG],
            "emission": [CANOEEmission.CO2, CANOEEmission.CH4],
            "factor": [51.88, 0.00099],
            "notes": ["", ""],
            "reference": ["ECCC", "ECCC"],
        }
    )


def _build(db: sqlite3.Connection, **frames: pd.DataFrame):
    supply = build_fuel_supply(
        import_costs=frames.get("import_costs", _import_costs()),
        distribution_costs=frames.get("distribution_costs", _distribution_costs()),
        upstream_factors=_upstream_factors(),
        combustion_factors=_combustion_factors(),
        lifetime=5,
        data_id=DATA_ID,
    )
    supply.build(db)
    return supply


def test_commodities(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute("SELECT name, flag, data_id FROM commodity").fetchall() == [
        ("F_ethos", "s", "FUELHR000"),
        ("F_ng", "p", "FUELHR000"),
    ]


def test_technologies_belong_to_the_fuel_and_consuming_sectors(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute(
        "SELECT tech, flag, sector, unlim_cap, annual FROM technology"
    ).fetchall() == [
        ("F_IMP_NG", "p", "fuel", 1, 1),
        ("F_C_NG", "p", "commercial", 1, 1),
        ("F_A_NG", "p", "agriculture", 1, 1),
    ]


def test_technologies_exist_where_they_have_a_cost(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute(
        "SELECT region, input_comm, tech, vintage, output_comm, efficiency"
        " FROM efficiency ORDER BY tech, region, vintage"
    ).fetchall() == [
        ("ON", "F_ng", "F_A_NG", 2025, "A_ng", 1.0),
        ("ON", "F_ng", "F_C_NG", 2025, "C_ng", 1.0),
        ("ON", "F_ng", "F_C_NG", 2030, "C_ng", 1.0),
        ("ON", "F_ethos", "F_IMP_NG", 2025, "F_ng", 1.0),
        ("ON", "F_ethos", "F_IMP_NG", 2030, "F_ng", 1.0),
        ("QC", "F_ethos", "F_IMP_NG", 2025, "F_ng", 1.0),
    ]


def test_variable_costs_by_period_with_the_period_as_vintage(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute(
        "SELECT region, period, tech, vintage, cost, units, notes, data_id"
        " FROM cost_variable WHERE tech = 'F_IMP_NG' ORDER BY region, period"
    ).fetchall() == [
        (
            "ON",
            2025,
            "F_IMP_NG",
            2025,
            3.9,
            "M$/PJ",
            "Lowest delivered price: electric power",
            "FUELHRON000",
        ),
        ("ON", 2030, "F_IMP_NG", 2030, 4.2, "M$/PJ", None, "FUELHRON000"),
        ("QC", 2025, "F_IMP_NG", 2025, 3.9, "M$/PJ", None, "FUELHRQC000"),
    ]


def test_lifetime_of_one_period(db: sqlite3.Connection):
    _ = _build(db)
    assert db.execute(
        "SELECT region, tech, lifetime FROM lifetime_tech WHERE tech = 'F_IMP_NG'"
    ).fetchall() == [("ON", "F_IMP_NG", 5.0), ("QC", "F_IMP_NG", 5.0)]


def test_upstream_emissions_on_imports_combustion_on_distribution(
    db: sqlite3.Connection,
):
    _ = _build(db)
    assert db.execute(
        "SELECT region, emis_comm, input_comm, tech, vintage, activity, units, notes"
        " FROM emission_activity ORDER BY tech, emis_comm, region, vintage"
    ).fetchall() == [
        ("ON", "ch4", "F_ng", "F_C_NG", 2025, 0.00099, "kt/PJ", "ECCC"),
        ("ON", "ch4", "F_ng", "F_C_NG", 2030, 0.00099, "kt/PJ", None),
        ("ON", "co2", "F_ng", "F_C_NG", 2025, 51.88, "kt/PJ", "ECCC"),
        ("ON", "co2", "F_ng", "F_C_NG", 2030, 51.88, "kt/PJ", None),
        (
            "ON",
            "co2",
            "F_ethos",
            "F_IMP_NG",
            2025,
            10.26,
            "kt/PJ",
            "Upstream emissions; ECCC Fuel LCA",
        ),
        ("ON", "co2", "F_ethos", "F_IMP_NG", 2030, 10.26, "kt/PJ", None),
        ("QC", "co2", "F_ethos", "F_IMP_NG", 2025, 10.26, "kt/PJ", None),
    ]


def test_declares_the_gases_written(db: sqlite3.Connection):
    supply = _build(db)
    assert set(supply.emissions) == {
        CANOEEmissionDeclaration(CANOESector.Fuel, CANOEEmission.CO2),
        CANOEEmissionDeclaration(CANOESector.Commercial, CANOEEmission.CO2),
        CANOEEmissionDeclaration(CANOESector.Commercial, CANOEEmission.CH4),
    }


def test_rejects_distribution_without_import(db: sqlite3.Connection):
    distribution = _costs(
        [(QC, 2030, CANOESector.Commercial, NG, 6.0, "")],
        ["region", "period", "sector", "fuel"],
    )
    with pytest.raises(ValueError, match="F_C_NG: no import of natural gas"):
        _ = _build(db, distribution_costs=distribution)


def test_rejects_two_costs_in_a_region_and_period(db: sqlite3.Connection):
    imports = pd.concat([_import_costs(), _import_costs().iloc[:1]])
    with pytest.raises(ValueError, match="more than one cost"):
        _ = _build(db, import_costs=imports)


def test_writes_nothing_without_imports(db: sqlite3.Connection):
    empty_imports = _import_costs().iloc[:0]
    empty_distribution = _distribution_costs().iloc[:0]
    supply = _build(
        db, import_costs=empty_imports, distribution_costs=empty_distribution
    )
    assert supply.emissions == []
    assert db.execute("SELECT count(*) FROM commodity").fetchone() == (0,)

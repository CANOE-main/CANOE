"""
Doctest setup for `canoe_objects`.

Every doctest in this package gets a fresh `db`: an in-memory CANOE v4.0 database with
the rows the examples rely on, the way canoe-base would have seeded them.

- data sets: `COMDOC001`, `COMDOCON001`, `COMDOCQC001`
  (`DatasetIdentifier(CANOESector.Commercial, "DOC", "001")`, with and without province)
- regions: ON, QC
- periods: 2020 (existing), 2025, 2030, 2035 (future)
- time slices: season D001, times of day H01 and H02
- commodity labels: `C_elc`, `C_ng` (fuels), `C_D_DOC`, `C_D_SPH`, `C_D_SPC`
  (demands) and `co2`, `ch4`, `n2o` (emissions, registered by the central emissions
  step in a pipeline run), so technologies can reference them without building the
  commodities first
"""

import sqlite3

import pytest
from canoe_schema.sql import get_sql_schema


def _example_database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("COMDOC001",), ("COMDOCON001",), ("COMDOCQC001",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, ?)",
        [(0, 2020, "e"), (1, 2025, "f"), (2, 2030, "f"), (3, 2035, "f")],
    )
    db.execute(
        "INSERT INTO time_season (sequence, season, segment_fraction) VALUES (0, 'D001', 1.0)"
    )
    db.executemany(
        "INSERT INTO time_of_day (sequence, tod, hours) VALUES (?, ?, 12)",
        [(0, "H01"), (1, "H02")],
    )
    db.executemany(
        "INSERT INTO commodity_label (commodity) VALUES (?)",
        [
            ("C_elc",),
            ("C_ng",),
            ("C_D_DOC",),
            ("C_D_SPH",),
            ("C_D_SPC",),
            ("co2",),
            ("ch4",),
            ("n2o",),
        ],
    )
    return db


@pytest.fixture(autouse=True)
def _doctest_database(doctest_namespace: dict[str, object]):
    doctest_namespace["db"] = _example_database()

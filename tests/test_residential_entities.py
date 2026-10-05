import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema
from canoe_schema.v4_0 import OperatorCode

from canoe.common import CANOEFuel, CANOEProvince, CANOESector
from canoe.common.naming import DatasetIdentifier
from canoe.common.time_slices import TimeSlice
from canoe.residential.end_uses import ResidentialEndUse
from canoe.residential.entities import (
    ExistingTechnologyParameters,
    build_end_use_demand,
    build_existing_technologies,
    build_existing_technology,
    end_use_demand_name,
)
from canoe.residential.technology_catalog import ExistingTechnology

ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
SPH, LGT = ResidentialEndUse.SpaceHeating, ResidentialEndUse.Lighting
WOOD_ELC = ExistingTechnology.SpaceHeatingWoodElectric
PERIODS = [2025, 2030]
DATA_ID = DatasetIdentifier(CANOESector.Residential, "HR", "000")
TIME_SLICES = [
    TimeSlice(hour=0, season="D001", tod="H01"),
    TimeSlice(hour=1, season="D001", tod="H02"),
]


@pytest.fixture
def db() -> sqlite3.Connection:
    """Base database with the rows canoe-base would have seeded"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO data_set (data_id) VALUES (?)",
        [("RESHR000",), ("RESHRON000",), ("RESHRQC000",)],
    )
    db.executemany("INSERT INTO region (region) VALUES (?)", [("ON",), ("QC",)])
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, ?)",
        [
            (0, 2015, "e"),
            (1, 2020, "e"),
            (2, 2025, "f"),
            (3, 2030, "f"),
            (4, 2035, "f"),
        ],
    )
    db.execute(
        "INSERT INTO time_season (sequence, season, segment_fraction) VALUES (0, 'D001', 1.0)"
    )
    db.executemany(
        "INSERT INTO time_of_day (sequence, tod, hours) VALUES (?, ?, 12)",
        [(0, "H01"), (1, "H02")],
    )
    return db


def _demand() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (ON, 2025, SPH, 300.0),
            (ON, 2030, SPH, 310.0),
            (QC, 2025, SPH, 0.0),
            (ON, 2025, LGT, 50.0),
        ],
        columns=["region", "period", "end_use", "demand"],
    )


def _dsd() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (ON, SPH, "D001", "H01", 0.75),
            (ON, SPH, "D001", "H02", 0.25),
            (ON, LGT, "D001", "H01", 0.0),
            (ON, LGT, "D001", "H02", 1.0),
        ],
        columns=["region", "end_use", "season", "tod", "dsd"],
    )


def _build(
    end_use: ResidentialEndUse, dsd: pd.DataFrame | None, db: sqlite3.Connection
):
    build_end_use_demand(
        end_use,
        _demand(),
        dsd,
        [ON, QC],
        PERIODS,
        TIME_SLICES,
        demand_notes="population",
        dsd_notes="ResStock",
        data_id=DATA_ID,
    ).build(db)


class TestEndUseDemand:
    def test_names_follow_the_naming_conventions(self):
        assert [end_use_demand_name(e) for e in ResidentialEndUse] == [
            "R_D_SPH",
            "R_D_SPC",
            "R_D_WAH",
            "R_D_LGT",
            "R_D_APP_REF",
            "R_D_APP_FRZ",
            "R_D_APP_DSH",
            "R_D_APP_CWSH",
            "R_D_APP_CDRY",
            "R_D_APP_COOK_RNG",
            "R_D_APP_OTH",
        ]

    def test_writes_positive_demand_in_its_units(self, db: sqlite3.Connection):
        _build(SPH, None, db)
        assert db.execute(
            "SELECT region, period, commodity, demand, units FROM demand"
        ).fetchall() == [
            ("ON", 2025, "R_D_SPH", 300.0, "PJ"),
            ("ON", 2030, "R_D_SPH", 310.0, "PJ"),
        ]
        assert db.execute(
            "SELECT name, flag, units, description FROM commodity"
        ).fetchall() == [("R_D_SPH", "d", "PJ", "demand for residential space heating")]
        assert db.execute(
            "SELECT count(*) FROM demand_specific_distribution"
        ).fetchone() == (0,)

    def test_distribution_in_every_period_zeros_included(self, db: sqlite3.Connection):
        _build(LGT, _dsd(), db)
        assert db.execute("SELECT units FROM demand").fetchall() == [("Glmy",)]
        assert db.execute(
            "SELECT region, period, tod, dsd FROM demand_specific_distribution "
            + "ORDER BY period, tod"
        ).fetchall() == [
            ("ON", 2025, "H01", 0.0),
            ("ON", 2025, "H02", 1.0),
            ("ON", 2030, "H01", 0.0),
            ("ON", 2030, "H02", 1.0),
        ]


def _existing_parameters() -> ExistingTechnologyParameters:
    """Dual wood-electric heating in Ontario (none in Quebec), two vintages"""
    vintages = [2015, 2020]
    return ExistingTechnologyParameters(
        efficiency=pd.DataFrame(
            [
                (r, WOOD_ELC, v, f, e)
                for r in (ON, QC)
                for v in vintages
                for f, e in ((CANOEFuel.Wood, 0.5), (CANOEFuel.Electricity, 1.0))
            ],
            columns=["region", "technology", "vintage", "fuel", "efficiency"],
        ),
        existing_capacity=pd.DataFrame(
            [
                (ON, WOOD_ELC, 2015, 10.0),
                (ON, WOOD_ELC, 2020, 12.0),
                (QC, WOOD_ELC, 2015, 0.0),
            ],
            columns=["region", "technology", "vintage", "capacity"],
        ),
        capacity_factor=pd.DataFrame(
            [
                (ON, WOOD_ELC, v, o, f)
                for v in vintages
                for o, f in ((OperatorCode.GE, 0.19), (OperatorCode.LE, 0.2))
            ],
            columns=["region", "technology", "vintage", "operator", "factor"],
        ),
        lifetime=pd.DataFrame(
            [(ON, WOOD_ELC, 15.0), (QC, WOOD_ELC, 15.0)],
            columns=["region", "technology", "lifetime"],
        ),
        fixed_cost=pd.DataFrame(
            [
                (ON, WOOD_ELC, 2015, 2025, 0.2),
                (ON, WOOD_ELC, 2020, 2025, 0.2),
                (ON, WOOD_ELC, 2020, 2030, 0.2),
            ],
            columns=["region", "technology", "vintage", "period", "cost"],
        ),
        efficiency_notes="t26",
        existing_capacity_notes="t21",
        capacity_factor_notes="activity / stock",
        lifetime_notes="AEO",
        fixed_cost_notes="EIA",
    )


def _build_existing(
    parameters: ExistingTechnologyParameters, db: sqlite3.Connection
) -> None:
    _build(SPH, None, db)  # The demand they output
    for entity in build_existing_technologies(
        [WOOD_ELC, ExistingTechnology.SpaceHeatingOil],
        parameters,
        [ON, QC],
        PERIODS,
        DATA_ID,
    ):
        entity.build(db)


class TestExistingTechnology:
    def test_names_are_the_catalog_names(self):
        frame = pd.DataFrame(
            columns=["region", "technology", "vintage", "fuel", "efficiency"]
        )
        for technology in ExistingTechnology:
            if technology == ExistingTechnology.OtherAppliances:
                continue
            parameters = replace(
                _existing_parameters(),
                existing_capacity=pd.DataFrame(
                    [(ON, technology, 2020, 1.0)],
                    columns=["region", "technology", "vintage", "capacity"],
                ),
                efficiency=frame,
            )
            entity = build_existing_technology(
                technology, parameters, [ON], PERIODS, DATA_ID
            )
            assert entity is not None
            assert entity.to_technology_entities()[0].name == technology.value

    def test_dual_system_takes_both_fuels_where_it_has_stock(
        self, db: sqlite3.Connection
    ):
        _build_existing(_existing_parameters(), db)
        assert db.execute(
            "SELECT tech, unlim_cap, annual, description FROM technology"
        ).fetchall() == [
            (
                "R_SPH_WOOD-ELC-EXS",
                0,
                1,
                "space heating - dual wood-electric - existing",
            )
        ]
        assert db.execute(
            "SELECT name, flag FROM commodity WHERE flag != 'd' ORDER BY name"
        ).fetchall() == [("R_elc", "p"), ("R_wood", "a")]
        assert db.execute(
            "SELECT region, input_comm, vintage, output_comm, efficiency, units "
            + "FROM efficiency ORDER BY input_comm, vintage"
        ).fetchall() == [
            ("ON", "R_elc", 2015, "R_D_SPH", 1.0, "PJ/PJ"),
            ("ON", "R_elc", 2020, "R_D_SPH", 1.0, "PJ/PJ"),
            ("ON", "R_wood", 2015, "R_D_SPH", 0.5, "PJ/PJ"),
            ("ON", "R_wood", 2020, "R_D_SPH", 0.5, "PJ/PJ"),
        ]
        assert db.execute(
            "SELECT region, vintage, capacity, units FROM existing_capacity"
        ).fetchall() == [("ON", 2015, 10.0, "kunit"), ("ON", 2020, 12.0, "kunit")]
        assert db.execute(
            "SELECT region, c2a, units FROM capacity_to_activity"
        ).fetchall() == [("ON", 1.0, "PJ/kunit.y")]
        assert db.execute("SELECT region, lifetime FROM lifetime_tech").fetchall() == [
            ("ON", 15.0)
        ]
        assert db.execute(
            "SELECT vintage, output_comm, operator, factor "
            + "FROM limit_annual_capacity_factor ORDER BY vintage, operator"
        ).fetchall() == [
            (2015, "R_D_SPH", "ge", 0.19),
            (2015, "R_D_SPH", "le", 0.2),
            (2020, "R_D_SPH", "ge", 0.19),
            (2020, "R_D_SPH", "le", 0.2),
        ]
        assert db.execute(
            "SELECT period, vintage, cost, units FROM cost_fixed ORDER BY period, vintage"
        ).fetchall() == [
            (2025, 2015, 0.2, "M$/kunit.y"),
            (2025, 2020, 0.2, "M$/kunit.y"),
            (2030, 2020, 0.2, "M$/kunit.y"),
        ]

    def test_left_out_without_stock(self):
        assert (
            build_existing_technology(
                ExistingTechnology.SpaceHeatingOil,
                _existing_parameters(),
                [ON, QC],
                PERIODS,
                DATA_ID,
            )
            is None
        )

    def test_no_fixed_cost_rows_without_fixed_cost(self, db: sqlite3.Connection):
        parameters = replace(
            _existing_parameters(),
            fixed_cost=pd.DataFrame(
                columns=["region", "technology", "vintage", "period", "cost"]
            ),
        )
        _build_existing(parameters, db)
        assert db.execute("SELECT count(*) FROM cost_fixed").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM existing_capacity").fetchone() == (2,)

    def test_missing_efficiency_of_a_fuel_fails(self):
        parameters = _existing_parameters()
        parameters = replace(
            parameters,
            efficiency=parameters.efficiency.loc[
                parameters.efficiency["fuel"].isin([CANOEFuel.Wood])
            ],
        )
        entity = build_existing_technology(
            WOOD_ELC, parameters, [ON, QC], PERIODS, DATA_ID
        )
        assert entity is not None
        with pytest.raises(ValueError, match="was set but has no values"):
            entity.to_technology_entities()[0].validate()

    def test_other_appliances_are_not_existing_capacity(self):
        with pytest.raises(ValueError, match="unlimited capacity"):
            build_existing_technology(
                ExistingTechnology.OtherAppliances,
                _existing_parameters(),
                [ON],
                PERIODS,
                DATA_ID,
            )

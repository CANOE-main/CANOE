"""
Structure of the industry sector under different configurations: which demands,
technologies, inputs, input splits and fuel imports it writes.

Each test runs the parameters and Temoa objects stages of `build_industry` (same
functions, same order) on small synthetic CEUD tables and writes them to an
in-memory database. The data:

- ON cement, 10 PJ: ELC 20%, NG 50%, COAL 20%, OTH 10%
- ON mining, 20 PJ: NG 100%
- QC cement, 5 PJ: ELC not published, NG 60%, PCK 30% (ELC gets the 10% left)
- QC mining: no energy use
- Atlantic cement, 8 PJ, all in NS: ELC 50%, COAL 50%
- Atlantic mining, 4 PJ, no StatCan share in NS
"""

import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from canoe_schema.sql import get_sql_schema
from canoe_schema.v4_0 import DataSet

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.ceud import CEUDEnergyUse
from canoe.common.naming import DatasetIdentifier
from canoe.industry.config import CANOEIndustryConfig
from canoe.industry.demand import align_demand_and_splits, compute_demand
from canoe.industry.energy_use import (
    compute_energy_use,
    compute_energy_use_by_source,
)
from canoe.industry.entities import IndustryEntities, build_industry_entities
from canoe.industry.input_splits import compute_ceud_shares, compute_input_splits
from canoe.industry.loaders import CEUD_INDUSTRY_SOURCES
from canoe.industry.subsectors import IndustrySubsector
from canoe.initializer import CANOEBaseConfig
from canoe.sector_config import resolve_sector_config

CONFIGURATION = Path(__file__).parents[1] / "configuration"
ON, QC, NS = (
    CANOEProvince.ONTARIO,
    CANOEProvince.QUEBEC,
    CANOEProvince.NOVA_SCOTIA,
)
CEMENT, MINING = IndustrySubsector.Cement, IndustrySubsector.Mining
PERIODS = [2025, 2030]
GROWTH = {2025: 1.0, 2030: 1.5}


def _table(total: float, shares: dict[CANOEFuel, float | None]) -> CEUDEnergyUse:
    """A CEUD table with `shares` (percent; None if not published) of `total`"""
    fuel_shares = [shares.get(fuel, 0.0) for fuel in CEUD_INDUSTRY_SOURCES.values()]
    return CEUDEnergyUse(
        total=total,
        by_source=pd.DataFrame(
            {
                "fuel": list(CEUD_INDUSTRY_SOURCES.values()),
                "energy_use": [
                    np.nan if s is None else total * s / 100 for s in fuel_shares
                ],
                "share": [np.nan if s is None else s for s in fuel_shares],
            },
            index=pd.Index(list(CEUD_INDUSTRY_SOURCES), name="source"),
        ),
    )


_F = CANOEFuel
CEUD = {
    ON: {
        CEMENT: _table(
            10, {_F.Electricity: 20, _F.NaturalGas: 50, _F.Coal: 20, _F.Other: 10}
        ),
        MINING: _table(20, {_F.NaturalGas: 100}),
    },
    QC: {
        CEMENT: _table(
            5, {_F.Electricity: None, _F.NaturalGas: 60, _F.PetroleumCoke: 30}
        ),
        MINING: _table(0, {}),
    },
    NS: {
        CEMENT: _table(8, {_F.Electricity: 50, _F.Coal: 50}),
        MINING: _table(4, {_F.NaturalGas: 100}),
    },
}
ATLANTIC_SHARES = {CEMENT: {NS: 1.0}, MINING: {NS: 0.0}}


@pytest.fixture
def base() -> CANOEBaseConfig:
    with (CONFIGURATION / "full-pipeline.toml").open("rb") as f:
        return CANOEBaseConfig.model_validate(tomllib.load(f)["compiler"]["base"])


def _config(base: CANOEBaseConfig, **overrides: Any) -> CANOEIndustryConfig:
    """The default industry config for ON, QC and NS over `PERIODS`, cement and
    mining only, with `overrides`"""
    with (CONFIGURATION / "industry-default.toml").open("rb") as f:
        raw = tomllib.load(f)
    others = {
        s.value: {"skip": True} for s in IndustrySubsector if s not in (CEMENT, MINING)
    }
    raw |= {
        "provinces": ["ON", "QC", "NS"],
        "future_periods": PERIODS,
        "subsectors": others,
    }
    subsectors = overrides.pop("subsectors", {})
    raw["subsectors"] = {**others, **subsectors}
    config = resolve_sector_config({**raw, **overrides}, base)
    assert isinstance(config, CANOEIndustryConfig)
    return config


def _build(cfg: CANOEIndustryConfig) -> tuple[sqlite3.Connection, IndustryEntities]:
    """The parameters and Temoa objects stages of `build_industry`, on `CEUD`"""
    subsectors = cfg.modelled_subsectors()
    ceud = {p: {s: CEUD[p][s] for s in subsectors} for p in cfg.provinces}
    energy_use = compute_energy_use(ceud, ATLANTIC_SHARES)
    energy_use_by_source = compute_energy_use_by_source(ceud, ATLANTIC_SHARES)

    shares = compute_ceud_shares(energy_use_by_source)
    demand_df = compute_demand(
        energy_use, energy_use_by_source, shares, GROWTH, cfg.other_fuels
    )
    input_fuels_of = {s: cfg.input_fuels_of(s) for s in subsectors}
    input_split_df = compute_input_splits(shares, input_fuels_of, cfg.future_periods)
    demand_df, input_split_df = align_demand_and_splits(
        demand_df, input_split_df, cfg.missing_data_behavior
    )

    data_id = DatasetIdentifier(CANOESector.Industry, "HR", cfg.data_version)
    db = _database(cfg, data_id)
    entities = build_industry_entities(
        demand_df,
        input_split_df,
        input_fuels_of,
        cfg.provinces,
        cfg.future_periods,
        cfg.input_split_operator,
        demand_notes="demand",
        split_notes="splits",
        lifetime=cfg.period_step,
        data_id=data_id,
    )
    entities.build(db)
    return db, entities


def _database(
    cfg: CANOEIndustryConfig, data_id: DatasetIdentifier
) -> sqlite3.Connection:
    """Base database with the regions, periods and data sets of `cfg`"""
    db = sqlite3.connect(":memory:")
    db.executescript(get_sql_schema("4.0"))
    db.executemany(
        "INSERT INTO region (region) VALUES (?)", [(p.short(),) for p in cfg.provinces]
    )
    db.executemany(
        "INSERT INTO time_period (sequence, period, flag) VALUES (?, ?, 'f')",
        list(
            enumerate([*cfg.future_periods, cfg.future_periods[-1] + cfg.period_step])
        ),
    )
    sql, params = DataSet.bulk_insert_or_ignore_sql(
        [
            DataSet(data_id=data_id.get_dataset_code(province=p))
            for p in [*cfg.provinces, None]
        ],
        include_nulls=True,
        include_defaults=True,
    )
    db.executemany(sql, params)
    return db


def _technologies(db: sqlite3.Connection) -> list[str]:
    return [t for (t,) in db.execute("SELECT tech FROM technology ORDER BY tech")]


def _inputs(db: sqlite3.Connection, tech: str) -> dict[str, list[str]]:
    """Region -> inputs of `tech` there"""
    inputs: dict[str, list[str]] = {}
    for region, commodity in db.execute(
        "SELECT DISTINCT region, input_comm FROM efficiency WHERE tech = ? "
        + "ORDER BY region, input_comm",
        (tech,),
    ):
        inputs.setdefault(region, []).append(commodity)
    return inputs


def _splits(db: sqlite3.Connection, tech: str, region: str) -> dict[str, float]:
    """Input -> split of `tech` in `region`, 2025"""
    return {
        commodity: round(proportion, 6)
        for commodity, proportion in db.execute(
            "SELECT input_comm, proportion FROM limit_tech_input_split_annual "
            + "WHERE tech = ? AND region = ? AND period = 2025",
            (tech, region),
        )
    }


def _demand(db: sqlite3.Connection, commodity: str) -> dict[tuple[str, int], float]:
    return {
        (region, period): round(demand, 6)
        for region, period, demand in db.execute(
            "SELECT region, period, demand FROM demand WHERE commodity = ?",
            (commodity,),
        )
    }


def _imports(imports: list[CANOEFuelImport]) -> dict[CANOEFuel, list[str]]:
    return {i.fuel: [p.short() for p in i.provinces] for i in imports}


class TestDeductOtherFuels:
    """Default configuration: every fuel, "Other" deducted from the demand"""

    def test_demands_and_technologies(self, base: CANOEBaseConfig):
        db, _ = _build(_config(base, other_fuels="deduct"))
        assert _technologies(db) == ["I_CEMENT", "I_MINING"]
        # ON cement less its 1 PJ of "Other"; NS cement all the Atlantic table
        assert _demand(db, "I_D_CEMENT") == {
            ("ON", 2025): 9.0,
            ("ON", 2030): 13.5,
            ("QC", 2025): 5.0,
            ("QC", 2030): 7.5,
            ("NS", 2025): 8.0,
            ("NS", 2030): 12.0,
        }
        # Mining: no energy use in QC, no StatCan share in NS
        assert _demand(db, "I_D_MINING") == {("ON", 2025): 20.0, ("ON", 2030): 30.0}

    def test_other_fuels_are_left_out(self, base: CANOEBaseConfig):
        db, entities = _build(_config(base, other_fuels="deduct"))
        assert entities.free_other_supply is None
        assert db.execute(
            "SELECT count(*) FROM commodity WHERE name IN ('I_oth', 'I_ethos')"
        ).fetchone() == (0,)
        # The 10% of "Other" is spread over the other fuels of ON cement
        assert _splits(db, "I_CEMENT", "ON") == {
            "I_elc": round(0.2 / 0.9, 6),
            "I_ng": round(0.5 / 0.9, 6),
            "I_coal": round(0.2 / 0.9, 6),
        }

    def test_inputs_follow_the_fuel_mix_of_each_province(self, base: CANOEBaseConfig):
        db, _ = _build(_config(base, other_fuels="deduct"))
        assert _inputs(db, "I_CEMENT") == {
            "NS": ["I_coal", "I_elc"],
            "ON": ["I_coal", "I_elc", "I_ng"],
            "QC": ["I_elc", "I_ng", "I_pck"],
        }
        # Electricity not published in QC: it gets the share left
        assert _splits(db, "I_CEMENT", "QC") == {
            "I_elc": 0.1,
            "I_ng": 0.6,
            "I_pck": 0.3,
        }

    def test_fuel_imports(self, base: CANOEBaseConfig):
        _, entities = _build(_config(base, other_fuels="deduct"))
        assert _imports(entities.fuel_imports()) == {
            CANOEFuel.Electricity: ["NS", "ON", "QC"],
            CANOEFuel.NaturalGas: ["ON", "QC"],
            CANOEFuel.Coal: ["NS", "ON"],
            CANOEFuel.PetroleumCoke: ["QC"],
        }


class TestFreeOtherFuels:
    def test_other_fuels_are_an_input_where_used(self, base: CANOEBaseConfig):
        db, entities = _build(_config(base, other_fuels="free"))
        assert _inputs(db, "I_CEMENT")["ON"] == ["I_coal", "I_elc", "I_ng", "I_oth"]
        assert "I_oth" not in _inputs(db, "I_CEMENT")["QC"]
        assert _splits(db, "I_CEMENT", "ON") == {
            "I_elc": 0.2,
            "I_ng": 0.5,
            "I_coal": 0.2,
            "I_oth": 0.1,
        }
        # The whole energy use is the demand
        assert _demand(db, "I_D_CEMENT")[("ON", 2025)] == 10.0
        assert entities.free_other_supply is not None

    def test_free_supply_where_other_fuels_are_used(self, base: CANOEBaseConfig):
        db, _ = _build(_config(base, other_fuels="free"))
        assert "I_FREE_OTH" in _technologies(db)
        assert _inputs(db, "I_FREE_OTH") == {"ON": ["I_ethos"]}
        assert db.execute(
            "SELECT count(*) FROM cost_variable WHERE tech = 'I_FREE_OTH'"
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT flag FROM commodity WHERE name = 'I_ethos'"
        ).fetchone() == ("s",)

    def test_other_fuels_are_not_a_fuel_import(self, base: CANOEBaseConfig):
        _, entities = _build(_config(base, other_fuels="free"))
        assert CANOEFuel.Other not in _imports(entities.fuel_imports())

    def test_no_free_supply_if_no_subsector_uses_other_fuels(
        self, base: CANOEBaseConfig
    ):
        db, entities = _build(
            _config(base, other_fuels="free", subsectors={"cement": {"skip": True}})
        )
        assert entities.free_other_supply is None
        assert _technologies(db) == ["I_MINING"]


class TestSubsectors:
    def test_skipped_subsector_is_left_out(self, base: CANOEBaseConfig):
        db, entities = _build(_config(base, subsectors={"mining": {"skip": True}}))
        assert _technologies(db) == ["I_CEMENT"]
        assert db.execute(
            "SELECT count(*) FROM commodity WHERE name = 'I_D_MINING'"
        ).fetchone() == (0,)
        assert [d.name for d in entities.demands] == ["I_D_CEMENT"]

    def test_subsector_fuels_override(self, base: CANOEBaseConfig):
        db, entities = _build(
            _config(
                base,
                other_fuels="deduct",
                subsectors={"cement": {"fuels": ["ELC", "NG"]}},
            )
        )
        # Coal and petroleum coke are spread over electricity and natural gas
        assert _splits(db, "I_CEMENT", "ON") == {
            "I_elc": round(0.2 / 0.7, 6),
            "I_ng": round(0.5 / 0.7, 6),
        }
        assert _splits(db, "I_CEMENT", "NS") == {"I_elc": 1.0}
        assert _splits(db, "I_CEMENT", "QC") == {
            "I_elc": round(0.1 / 0.7, 6),
            "I_ng": round(0.6 / 0.7, 6),
        }
        # Mining keeps the sector's fuels; no subsector takes coal any more
        assert set(_imports(entities.fuel_imports())) == {
            CANOEFuel.Electricity,
            CANOEFuel.NaturalGas,
        }
        assert db.execute(
            "SELECT count(*) FROM commodity WHERE name = 'I_coal'"
        ).fetchone() == (0,)

    def test_sector_fuels(self, base: CANOEBaseConfig):
        db, _ = _build(_config(base, other_fuels="deduct", fuels=["NG", "COAL"]))
        assert _inputs(db, "I_CEMENT") == {
            "NS": ["I_coal"],
            "ON": ["I_coal", "I_ng"],
            "QC": ["I_ng"],
        }
        assert _inputs(db, "I_MINING") == {"ON": ["I_ng"]}

    def test_subsector_without_its_fuels_is_reported(self, base: CANOEBaseConfig):
        # No petroleum coke in ON or NS cement
        overrides: dict[str, Any] = {"subsectors": {"cement": {"fuels": ["PCK"]}}}
        with pytest.raises(ValueError, match="No fuel of cement"):
            _build(_config(base, missing_data_behavior="error", **overrides))
        db, _ = _build(_config(base, missing_data_behavior="warning", **overrides))
        assert _inputs(db, "I_CEMENT") == {"QC": ["I_pck"]}
        assert set(_demand(db, "I_D_CEMENT")) == {("QC", 2025), ("QC", 2030)}


class TestValidity:
    @pytest.mark.parametrize("other_fuels", ["deduct", "free"])
    @pytest.mark.parametrize(
        "overrides",
        [
            {},
            {"fuels": ["ELC", "NG"]},
            {"subsectors": {"cement": {"fuels": ["COAL", "PCK"]}}},
        ],
    )
    def test_every_demand_can_be_met(
        self, base: CANOEBaseConfig, other_fuels: str, overrides: dict[str, Any]
    ):
        db, _ = _build(_config(base, other_fuels=other_fuels, **overrides))
        # Every demand has a technology with inputs there, whose splits add up to 1
        for region, period, commodity in db.execute(
            "SELECT region, period, commodity FROM demand"
        ).fetchall():
            (total,) = db.execute(
                "SELECT sum(s.proportion) FROM limit_tech_input_split_annual s "
                + "JOIN efficiency e ON e.region = s.region AND e.tech = s.tech "
                + "AND e.input_comm = s.input_comm AND e.vintage = s.period "
                + "WHERE s.region = ? AND s.period = ? AND e.output_comm = ?",
                (region, period, commodity),
            ).fetchone()
            assert total == pytest.approx(1.0), (region, period, commodity)

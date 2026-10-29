"""
Clean Electricity Regulations (CER): a cap on the emission intensity of each fossil
generator, with credits for the emissions above it at the carbon price.

The cap is on net CO2: the direct emissions of the generator plus the upstream
emissions of the fuel it burns, a dummy emission commodity (`co2_cer`) written as
emission activities of the generators. The regulation itself is the
`clean_electricity_regulation` table, which the Temoa `carbon_markets` extension reads.
"""

import sqlite3

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from canoe.common.naming import DatasetIdentifier

_COMMODITY = "co2_cer"

_TABLE = """
CREATE TABLE IF NOT EXISTS clean_electricity_regulation
(
    region        TEXT,
    period        INTEGER,
    tech          TEXT,
    vintage       INTEGER,
    emis_comm     TEXT,
    cap           REAL NOT NULL,
    credit_limit  REAL NOT NULL DEFAULT 0,
    credit_cost   REAL NOT NULL DEFAULT 0,
    units         TEXT,
    notes         TEXT,
    PRIMARY KEY (region, period, tech, vintage, emis_comm),
    FOREIGN KEY (period) REFERENCES time_period (period),
    FOREIGN KEY (vintage) REFERENCES time_period (period),
    FOREIGN KEY (emis_comm) REFERENCES commodity_label (commodity)
)
"""


class CleanElectricityRegulationConfig(BaseModel):
    """CER, `[compiler.mmcf2026.clean_electricity_regulation]` in TOML."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    start_period: int = 2035
    """First period the regulation applies."""

    emission_intensity_cap: float = Field(default=65, ge=0)
    """Emission intensity cap, t/GWh, until the last period."""

    final_emission_intensity_cap: float = Field(default=0, ge=0)
    """Emission intensity cap, t/GWh, in the last period."""

    credit_limit: float = Field(default=35, ge=0)
    """Emission intensity above the cap that credits can cover, t/GWh, until the last
    period."""

    final_credit_limit: float = Field(default=42, ge=0)
    """The same, in the last period."""

    carbon_price: dict[int, float] = {2035: 140, 2040: 140, 2045: 140}
    """Price of a credit, nominal CAD/t, of each period from `start_period`."""

    price_deflator: float = Field(default=1.2418, gt=0)
    """Price level of 2026 over that of the model currency year (2020, Bank of Canada)."""

    inflation_rate: float = 0.02
    """Yearly inflation after `price_base_year` (the Bank of Canada target)."""

    price_base_year: int = 2026
    """Year `price_deflator` applies to, and the start of the yearly inflation."""

    regulated_life: int = 25
    """Years after its vintage a generator is regulated from, unless regulated from
    the start by the options below."""

    regulated_from_vintage: int = 2030
    """Generators of this vintage or later are regulated from the start."""

    always_regulated_techs: list[str] = ["COAL"]
    """Generators whose name contains one of these are regulated from the start."""

    excluded_techs: list[str] = ["RFIT"]
    """Generators whose name contains one of these have no direct emissions counted
    (retrofits)."""

    generator_prefix: str = "E_"
    """Prefix of the generator technologies."""

    fuel_supply_prefix: str = "F_E_"
    """Prefix of the technologies supplying fuel to generators, whose emissions are
    the upstream ones."""

    @model_validator(mode="after")
    def _check_prices(self):
        if not self.carbon_price:
            raise ValueError("carbon_price needs at least one period")
        return self


def apply(
    conn: sqlite3.Connection,
    config: CleanElectricityRegulationConfig,
    periods: list[int],
    data_id: DatasetIdentifier,
) -> None:
    dataset = data_id.get_dataset_code()
    base_period = periods[0]

    conn.execute(_TABLE)
    conn.execute("REPLACE INTO commodity_label(commodity) VALUES (?)", (_COMMODITY,))
    conn.execute(
        """
        REPLACE INTO commodity(name, flag, description, data_id)
        VALUES (?, 'e', 'CER dummy co2 duplicate for policy modelling', ?)
        """,
        (_COMMODITY, dataset),
    )

    fuel_like = config.fuel_supply_prefix + "%"
    generator_like = config.generator_prefix + "%"
    fuel_emissions = pd.read_sql_query(
        """
        SELECT DISTINCT output_comm, activity FROM emission_activity
        WHERE tech LIKE ? AND emis_comm = 'co2' AND vintage = ?
        """,
        conn,
        params=(fuel_like, base_period),
    ).drop_duplicates("output_comm")
    efficiency = pd.read_sql_query(
        """
        SELECT DISTINCT region, input_comm, tech, vintage, output_comm, efficiency
        FROM efficiency
        WHERE tech LIKE ? AND input_comm IN (
            SELECT DISTINCT output_comm FROM emission_activity
            WHERE tech LIKE ? AND emis_comm = 'co2' AND vintage = ?
        )
        """,
        conn,
        params=(generator_like, fuel_like, base_period),
    )
    excluded = "".join(" AND tech NOT LIKE ?" for _ in config.excluded_techs)
    direct = (
        pd.read_sql_query(
            f"""
            SELECT DISTINCT tech, vintage, activity FROM emission_activity
            WHERE tech LIKE ?{excluded} AND emis_comm = 'co2'
            """,
            conn,
            params=(generator_like, *(f"%{t}%" for t in config.excluded_techs)),
        )
        .groupby(["tech", "vintage"], as_index=False)["activity"]
        .sum()
        .rename(columns={"activity": "direct"})
    )

    # Net CO2 of the generator: the upstream emissions of its fuel and its own
    net = (
        efficiency.merge(
            fuel_emissions.rename(
                columns={"output_comm": "input_comm", "activity": "fuel"}
            ),
            on="input_comm",
        )
        .merge(direct, on=["tech", "vintage"], how="left")
        .fillna({"direct": 0})
    )
    net["activity"] = net["fuel"] / net["efficiency"] + net["direct"]
    net["emis_comm"] = _COMMODITY
    net["units"] = "kt/PJ"
    net["notes"] = "CER net co2 dummy emitter"
    net["data_id"] = dataset
    emission_activity = net[
        [
            "region",
            "emis_comm",
            "input_comm",
            "tech",
            "vintage",
            "output_comm",
            "activity",
            "units",
            "notes",
            "data_id",
        ]
    ]
    emission_activity.to_sql("emission_activity", conn, if_exists="append", index=False)

    last_period = periods[-1]
    kt_per_gw = 8760 / 1000  # t/GWh to kt/GW-year
    for period in periods:
        if period < config.start_period:
            continue
        if period not in config.carbon_price:
            raise ValueError(f"carbon_price has no price for the period {period}")
        final = period == last_period
        price = config.carbon_price[period] / config.price_deflator
        if period > config.price_base_year:
            price /= (1 + config.inflation_rate) ** (period - config.price_base_year)

        rows = emission_activity.assign(period=period)
        always = pd.Series(False, index=rows.index)
        for name in config.always_regulated_techs:
            always |= rows["tech"].str.contains(name, regex=False)
        rows = rows[
            (rows["period"] >= rows["vintage"] + config.regulated_life)
            | (rows["vintage"] >= config.regulated_from_vintage)
            | always
            | final
        ]
        regulation = pd.DataFrame(
            {
                "region": rows["region"],
                "period": period,
                "tech": rows["tech"],
                "vintage": rows["vintage"],
                "emis_comm": _COMMODITY,
                "cap": (
                    config.final_emission_intensity_cap
                    if final
                    else config.emission_intensity_cap
                )
                * kt_per_gw,
                "credit_limit": (
                    config.final_credit_limit if final else config.credit_limit
                )
                * kt_per_gw,
                "credit_cost": price / 1000,  # $/t to M$/kt
                "notes": "CER regulations by vintage and period",
            }
        )
        regulation.to_sql(
            "clean_electricity_regulation", conn, if_exists="append", index=False
        )

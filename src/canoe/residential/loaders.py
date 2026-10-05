"""
Loaders for the datasets used only by the residential sector.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, sections, row labels, units), so when a source changes shape the
error points to the function to fix. They return tidy frames (or series); everything
downstream is independent of the source layout.

Most sources are not usable from the data lake cache yet and are read from `data/`,
copied from the previous module (see `DATA_LAKE_REQUESTS.md`):

- `data/ceud/res_<province>_e_<table>.csv`: NRCan CEUD residential tables as the
  previous module cached them (full precision, one set per province, the Atlantic
  provinces included).
- `data/rsmess.xlsx`: EIA AEO Residential Demand Module technology menu.
- `data/aeo_lighting_data.csv`, `data/existing_lighting_technologies.csv`:
  hand-entered lighting data of the previous module.
- `data/statcan_*.csv`: StatCan tables as the previous module cached them; the
  projections table is an extract (see `data/make_statcan_17100057_extract.py`).
"""

import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince, GoldConnectorConfig

from .end_uses import ResidentialEndUse

# ----------------------------------------------------------------------------
# NRCan CEUD residential tables and Energy Use Data Handbook
# ----------------------------------------------------------------------------


def _clean_label(label: object) -> str:
    """
    Row label as the previous module matched it: lower case, without footnote marks
    (digits 1-9) or symbols other than `- /()–`, e.g. "Other Appliances3" -> "other
    appliances".
    """
    kept = "".join(c for c in str(label) if c in "- /()–" or c.isalnum())
    return " ".join("".join(c for c in kept if c not in "123456789").lower().split())


class _NRCanTable:
    """
    A NRCan table with the layout of the CEUD and handbook workbooks: row labels in
    column "Unnamed: 1" and one column per year. Values come in blocks: a header row
    (a label with no numbers, e.g. "Energy Use by System Type (PJ)") followed by its
    rows, up to a blank row. Labels are compared after `_clean_label`, so they can
    be written as published.
    """

    def __init__(self, table: pd.DataFrame, dataset: str):
        self.dataset: str = dataset
        years = [c for c in table.columns if str(c).isdigit()]
        # Values NRCan publishes instead of a number (not available, confidential,
        # nil)
        missing_markers = {"n.a.", "X", "x", "..", "–", "-"}

        def number(raw: object) -> float:
            if raw is None or (isinstance(raw, float) and np.isnan(raw)):
                return np.nan
            if str(raw).strip() in missing_markers:
                return np.nan
            try:
                return float(raw)  # pyright: ignore[reportArgumentType]
            except ValueError:
                raise ValueError(f"{dataset}: unexpected value {raw!r}") from None

        self.numbers: pd.DataFrame = pd.DataFrame(
            table[years].map(number).to_numpy(dtype=float),
            columns=[int(y) for y in years],
        )
        self.labels: list[str | None] = [
            None if pd.isna(label) else _clean_label(label)
            for label in table["Unnamed: 1"]
        ]
        self.empty: list[bool] = [
            bool(np.isnan(row).all()) for row in self.numbers.to_numpy()
        ]

    def blocks(self, header: str) -> list[pd.DataFrame]:
        """
        Every block under a header row labelled `header`: its rows with numbers
        (index: label, columns: years), up to the next blank row. Rows with no
        numbers inside a block (sub-headers such as "Dual Systems") are left out.
        """
        found: list[pd.DataFrame] = []
        for start, label in enumerate(self.labels):
            if label != _clean_label(header) or not self.empty[start]:
                continue
            rows: list[int] = []
            for row in range(start + 1, len(self.labels)):
                if self.labels[row] is None and self.empty[row]:
                    break
                if not self.empty[row]:
                    rows.append(row)
            block = self.numbers.loc[rows]
            block.index = [self.labels[row] for row in rows]
            found.append(block)
        return found

    def block(self, header: str) -> pd.DataFrame:
        """The block under the only header row labelled `header`, see `blocks`"""
        found = self.blocks(header)
        if len(found) != 1:
            raise ValueError(
                f"{self.dataset}: expected one block {header!r}, found {len(found)}"
            )
        return found[0]

    def row(self, label: str, year: int) -> float:
        """Value in `year` of the only row labelled `label`"""
        rows = [i for i, own in enumerate(self.labels) if own == _clean_label(label)]
        if len(rows) != 1:
            raise ValueError(
                f"{self.dataset}: expected one row {label!r}, found {len(rows)}"
            )
        return float(self.year(self.numbers.loc[[rows[0]]], year).iloc[0])

    def year(self, block: pd.DataFrame, year: int) -> pd.Series:
        """Column `year` of a block"""
        if year not in block.columns:
            raise ValueError(
                f"{self.dataset}: year {year} not in the table. "
                + f"Years: {list(block.columns)}"
            )
        return pd.Series(block[year])


def _read_ceud_table(province: CANOEProvince, table: int) -> _NRCanTable:
    dataset = f"res_{province.get_nrcan_province_code().lower()}_e_{table}"
    resource = files("canoe.residential").joinpath(f"data/ceud/{dataset}.csv")
    with resource.open("rb") as f:
        return _NRCanTable(pd.read_csv(f, index_col=0, dtype=str), dataset)


def get_ceud_lighting_energy_use(province: CANOEProvince, data_year: int) -> float:
    """Total lighting energy use (PJ), CEUD table 3."""
    table = _read_ceud_table(province, 3)
    return table.row("Total Lighting Energy Use2 (PJ)", data_year)


def get_ceud_space_cooling_energy_use(
    province: CANOEProvince, data_year: int
) -> pd.Series:
    """Space cooling energy use (PJ) by cooling system type ("room", "central"),
    CEUD table 4."""
    table = _read_ceud_table(province, 4)
    return table.year(table.block("Energy Use by Cooling System Type (PJ)"), data_year)


def get_ceud_space_heating_energy_use(
    province: CANOEProvince, data_year: int
) -> pd.Series:
    """
    Space heating energy use (PJ) by heating system type, CEUD table 8: oil and
    natural gas by efficiency ("heating oil – normal efficiency", ...), "electric",
    "heat pump", "other" (LPG), "wood" and the dual systems ("wood/electric",
    "wood/heating oil", "natural gas/electric", "heating oil/electric").
    """
    table = _read_ceud_table(province, 8)
    return table.year(table.block("Energy Use by System Type (PJ)"), data_year)


def get_ceud_water_heating_energy_use(
    province: CANOEProvince, data_year: int
) -> pd.Series:
    """Water heating energy use (PJ) by energy source ("electricity", "natural gas",
    "heating oil", "other" (LPG), "wood"), CEUD table 10."""
    table = _read_ceud_table(province, 10)
    return table.year(table.block("Energy Use by Energy Source (PJ)"), data_year)


def get_ceud_appliance_energy_use(province: CANOEProvince, data_year: int) -> pd.Series:
    """Appliance energy use (PJ) by appliance type ("refrigerator", "freezer",
    "dishwasher", "clothes washer", "clothes dryer", "range", "other appliances"),
    CEUD table 13."""
    table = _read_ceud_table(province, 13)
    return table.year(table.block("Energy Use by Appliance Type (PJ)"), data_year)


def get_ceud_household_shares(province: CANOEProvince, data_year: int) -> pd.Series:
    """
    Share of households (%) by building type ("single detached", "single attached",
    "apartments", "mobile homes"), CEUD table 14.
    """
    table = _read_ceud_table(province, 14)
    # Two blocks are headed "Shares (%)": by building type (first) and by energy
    # source
    shares = table.blocks("Shares (%)")
    by_building_type = table.block("Households by Building Type (thousands)")
    if len(shares) != 2 or list(shares[0].index) != list(by_building_type.index):
        raise ValueError(f"{table.dataset}: no shares by building type")
    return table.year(shares[0], data_year)


def get_ceud_heating_system_stock(province: CANOEProvince, data_year: int) -> pd.Series:
    """Heating system stock (thousands) by heating system type (the types of
    `get_ceud_space_heating_energy_use`), CEUD table 21."""
    table = _read_ceud_table(province, 21)
    return table.year(
        table.block("Heating System Stock by Heating System Type (thousands)"),
        data_year,
    )


def get_ceud_heating_system_efficiencies(
    province: CANOEProvince, data_year: int
) -> pd.DataFrame:
    """
    Stock efficiency (%) of each heating system type, CEUD table 26.

    Returns columns `system` (the types of `get_ceud_space_heating_energy_use`),
    `fuel` (for dual systems, the fuel the efficiency is of: "electricity", "wood",
    "heating oil" or "natural gas"; None for the others) and `efficiency` (%).

    The dual systems have a block each, with a row per fuel; their blocks name the
    fuels in another order than tables 8 and 21, so they are matched by name (the
    previous module matched them by position).
    """
    # Block of each dual system -> its name in tables 8 and 21 (the fuels in another
    # order)
    dual_systems = {
        "Dual Heating Systems Electric/Wood": "wood/electric",
        "Dual Heating Systems Heating Oil/Wood": "wood/heating oil",
        "Dual Heating Systems Electric/Natural Gas": "natural gas/electric",
        "Dual Heating Systems Electric/Heating Oil": "heating oil/electric",
    }
    table = _read_ceud_table(province, 26)
    single = table.year(
        table.block("Heating System Stock Efficiencies by System Type (%)"), data_year
    )
    frames = [
        pd.DataFrame({"system": single.index, "fuel": None, "efficiency": single})
    ]
    for header, system in dual_systems.items():
        dual = table.year(table.block(header), data_year)
        frames.append(
            pd.DataFrame({"system": system, "fuel": dual.index, "efficiency": dual})
        )
    return pd.concat(frames, ignore_index=True)


@dataclass(frozen=True)
class CEUDCoolingSystems:
    """
    Cooling systems of a province, CEUD table 27.

    Parameters
    ----------
    stock : pd.Series
        Stock (thousands) by cooling system type ("room", "central"), in the data
        year.
    efficiencies : pd.DataFrame
        Columns `system` ("room", "central"), `kind` ("new unit" or "stock"),
        `metric` ("EER" for room, "SEER" for central units), `year` and
        `efficiency` (in the metric), every year of the table.
    """

    stock: pd.Series
    efficiencies: pd.DataFrame


def get_ceud_cooling_systems(
    province: CANOEProvince, data_year: int
) -> CEUDCoolingSystems:
    """Cooling system stock and efficiencies, CEUD table 27, see `CEUDCoolingSystems`."""
    table = _read_ceud_table(province, 27)
    stock = table.year(table.block("System Stock by Type (thousands)"), data_year)
    frames: list[pd.DataFrame] = []
    for kind, header in (
        ("new unit", "New Unit Efficiencies"),
        ("stock", "Stock Efficiencies"),
    ):
        values = table.block(header)
        # Labels carry the metric: "room (eer)", "central (seer)"
        system_of: dict[str, str] = {}
        metric_of: dict[str, str] = {}
        for label in values.index:
            match = re.fullmatch(r"(\w+) \((\w+)\)", str(label))
            if match is None:
                raise ValueError(f"{table.dataset}: unexpected label {label!r}")
            system_of[label] = match.group(1)
            metric_of[label] = match.group(2).upper()
        long = values.reset_index(names="label").melt(
            id_vars="label", var_name="year", value_name="efficiency"
        )
        frames.append(
            long.assign(
                system=[system_of[label] for label in long["label"]],
                kind=kind,
                metric=[metric_of[label] for label in long["label"]],
            ).reindex(columns=["system", "kind", "metric", "year", "efficiency"])
        )
    return CEUDCoolingSystems(
        stock=stock, efficiencies=pd.concat(frames, ignore_index=True)
    )


def get_ceud_water_heater_stock(province: CANOEProvince, data_year: int) -> pd.Series:
    """Water heater stock (thousands) by energy source ("electricity", "natural gas",
    "heating oil", "steam", "other" (LPG), "wood"), CEUD table 28."""
    table = _read_ceud_table(province, 28)
    return table.year(
        table.block("Water Heater Stock by Energy Source (thousands)"), data_year
    )


def get_ceud_appliance_stock(province: CANOEProvince, data_year: int) -> pd.DataFrame:
    """
    Appliance stock (thousands) by appliance type and energy source, CEUD table 31.

    Returns columns `appliance` ("refrigerator", ..., "range", "other appliances"),
    `fuel` ("electricity", or "natural gas" for clothes dryers and ranges) and
    `stock` (thousands).
    """
    table = _read_ceud_table(province, 31)
    frames: list[pd.DataFrame] = []
    for fuel, header in (
        ("electricity", "Stock of Electric Appliances (thousands)"),
        ("natural gas", "Stock of Natural Gas Appliances (thousands)"),
    ):
        stock = table.year(table.block(header), data_year)
        frames.append(
            pd.DataFrame({"appliance": stock.index, "fuel": fuel, "stock": stock})
        )
    return pd.concat(frames, ignore_index=True)


def get_handbook_appliance_consumption(
    cache_config: GoldConnectorConfig,
) -> pd.DataFrame:
    """
    Unit energy consumption (kWh/year) of the stock of appliances in 2021, NRCan
    Energy Use Data Handbook table res_00_16 (cached as `nrcan_res_handbook`).

    2021 is the last year of the cached edition, the one the previous module used (the
    link to the 2022 edition was broken).

    Returns columns `appliance` ("refrigerator", ..., "clothes dryer", "range"),
    `fuel` ("electricity", or "natural gas" for clothes dryers and ranges) and
    `unit_consumption` (kWh/year).
    """
    dataset = "nrcan_res_handbook"
    year = 2021
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / dataset / f"{dataset}_{cache_config.cache_date}.parquet"
    logger.debug(f"Loading cached handbook table {dataset} ({year})")
    table = _NRCanTable(pd.read_parquet(file_path), dataset)
    frames: list[pd.DataFrame] = []
    for fuel, header in (
        ("electricity", "UEC1 for Stock of Electric Appliances (kWh/year)b"),
        ("natural gas", "UEC1 for Stock of Natural Gas Appliances (kWh/year)b"),
    ):
        uec = table.year(table.block(header), year)
        frames.append(
            pd.DataFrame(
                {"appliance": uec.index, "fuel": fuel, "unit_consumption": uec}
            )
        )
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------------
# EIA AEO Residential Demand Module technology menu
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AEOTechnologyMenu:
    """
    The AEO residential technology menu (`rsmess`).

    Parameters
    ----------
    classes : pd.DataFrame
        Equipment classes (sheet RSCLASS), one row per (class, end use): columns
        `equipment_class` (e.g. "NG_FA"), `end_use` (AEO end use number: 1 space
        heating, 2 space cooling, 3 clothes washers, 4 dish washers, 5 water
        heating, 6 cooking, 7 clothes drying, 8 refrigeration, 9 freezing),
        `furnace_fan` (0/1), `base_efficiency`, `efficiency_metric` (e.g. "AFUE",
        "COP", "UEF", "kWh/cycle") and the Weibull lifetime parameters
        `weibull_lambda`, `weibull_k` (years). Heat pumps have a row per end use.
    equipment : pd.DataFrame
        Equipment (sheet RSMEQP), one row per (equipment, census division, years):
        columns `equipment` (e.g. "NG_FA2"), `end_use`, `census_division` (1-9,
        11 for national rows), `first_year`, `last_year`, `efficiency` (in the
        class's metric) and `replacement_cost` (USD of `cost_dollar_year` per
        unit).
    cost_dollar_year : int
        Year of the US dollars of the costs.
    """

    classes: pd.DataFrame
    equipment: pd.DataFrame
    cost_dollar_year: int


def get_aeo_technology_menu() -> AEOTechnologyMenu:
    """
    The AEO residential technology menu, see `AEOTechnologyMenu`.

    Each sheet has a table under a header row, followed by rows of the model's
    variable names; tables are found by their header and rows kept where the end
    use is a number.
    """
    dataset = "rsmess.xlsx"
    resource = files("canoe.residential").joinpath(f"data/{dataset}")
    with resource.open("rb") as f:
        sheets = pd.read_excel(f, sheet_name=["RSCLASS", "RSMEQP"], header=None)

    def table(sheet: str, header_cell: str) -> pd.DataFrame:
        raw = sheets[sheet]
        header_rows = raw.index[(raw == header_cell).any(axis=1)]
        if len(header_rows) != 1:
            raise ValueError(
                f"{dataset}: no single header row with {header_cell!r} in {sheet}"
            )
        header = pd.Series(raw.loc[header_rows[0]])
        named = header.notna().to_numpy()
        body = raw.loc[header_rows[0] + 1 :, named].set_axis(
            header[named].tolist(), axis=1
        )
        is_row = pd.Series(
            pd.to_numeric(body["End Use"], errors="coerce"), index=body.index
        ).notna()
        return body[is_row].reset_index(drop=True)

    classes = table("RSCLASS", "Weibull K")
    equipment = table("RSMEQP", "Tech Name")

    # "<year> | Equipment cost dollar year" above the RSMEQP table
    raw = sheets["RSMEQP"]
    cell = raw.map(lambda v: str(v).startswith("Equipment cost dollar year"))
    rows, columns = np.nonzero(cell.to_numpy())
    if len(rows) != 1:
        raise ValueError(f"{dataset}: no single 'Equipment cost dollar year' in RSMEQP")
    cost_dollar_year = int(raw.iat[rows[0], columns[0] - 1])

    return AEOTechnologyMenu(
        classes=pd.DataFrame(
            {
                "equipment_class": classes["Equipment Class Name"],
                "end_use": classes["End Use"].astype(int),
                "furnace_fan": classes["Furnace Fan Flag"].astype(int),
                "base_efficiency": classes["Base Efficiency"].astype(float),
                "efficiency_metric": classes["Efficiency Metric"],
                "weibull_lambda": classes["Weibull λ"].astype(float),
                "weibull_k": classes["Weibull K"].astype(float),
            }
        ),
        equipment=pd.DataFrame(
            {
                "equipment": equipment["Tech Name"],
                "end_use": equipment["End Use"].astype(int),
                "census_division": equipment["Census Division"].astype(int),
                "first_year": equipment["First Year"].astype(int),
                "last_year": equipment["Last Year"].astype(int),
                "efficiency": equipment["Efficiency"].astype(float),
                "replacement_cost": equipment["Replacement Cost"].astype(float),
            }
        ),
        cost_dollar_year=cost_dollar_year,
    )


# ----------------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------------


def get_aeo_lighting_data() -> pd.DataFrame:
    """
    Lamp data from the AEO (hand-entered by the previous module): efficacy (lm/W),
    lamp life (hours), installation cost (USD2022/klm) and maintenance cost
    (USD2022/klmy) of each lamp.

    Returns columns `lamp` (code: "inc", "hal", "cfl", "cfl-hef", "led", "led-hef",
    "t12"), `metric` ("efficacy", "lamp_life", "cost_install", "cost_maintain"),
    `units`, `year` (<NA> for the existing stock, else the year of the projection)
    and `value`. Missing values are left out.
    """
    resource = files("canoe.residential").joinpath("data/aeo_lighting_data.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, encoding="utf-8-sig")
    long = df.melt(
        id_vars=["code", "metric", "units"], var_name="column", value_name="value"
    ).dropna(subset=["value"])
    year = pd.Series(
        pd.to_numeric(long["column"].where(long["column"] != "existing")),
        index=long.index,
    ).astype("Int64")
    return (
        long.assign(lamp=long["code"], year=year)
        .reindex(columns=["lamp", "metric", "units", "year", "value"])
        .reset_index(drop=True)
    )


def get_ontario_lighting_shares() -> pd.DataFrame:
    """
    Shares of bulb types in the Ontario lighting stock, by housing type (IESO 2018
    Ontario Residential End-Use Survey, hand-entered by the previous module).

    Returns columns `lamp` (code: "inc", "hal", "cfl", "led", "t12"),
    `single_family` and `multi_family` (fractions of the stock), `statcan_category`
    (its type in StatCan Table 38-10-0048-01) and `oldest_vintage` (<NA> if none:
    the first year the bulb type is in the existing stock).
    """
    resource = files("canoe.residential").joinpath(
        "data/existing_lighting_technologies.csv"
    )
    with resource.open("rb") as f:
        df = pd.read_csv(f, encoding="utf-8-sig")
    return pd.DataFrame(
        {
            "lamp": df["code"],
            "single_family": df["on_share_sf"],
            "multi_family": df["on_share_mf"],
            "statcan_category": df["statcan_category"],
            "oldest_vintage": df["oldest_vint"].astype("Int64"),
        }
    )


def get_statcan_energy_saving_lights(provinces: list[CANOEProvince]) -> pd.DataFrame:
    """
    Households using each type of energy-saving light (%), StatCan Table
    38-10-0048-01, as the previous module cached it.

    Returns columns `province`, `light_type` (e.g. "Compact fluorescent lights"),
    `year` and `percent`.
    """
    resource = files("canoe.residential").joinpath("data/statcan_38100048.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    province_of = {p.value: p for p in provinces}
    rows = df[df["GEO"].isin(province_of)]
    return pd.DataFrame(
        {
            "province": [province_of[geo] for geo in rows["GEO"]],
            "light_type": rows["Type of energy-saving light"],
            "year": rows["REF_DATE"].astype(int),
            "percent": rows["VALUE"].astype(float),
        }
    ).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Population
# ----------------------------------------------------------------------------


def get_statcan_population_estimates() -> pd.DataFrame:
    """
    Population on January 1st of each year, by geography (Canada, provinces and
    territories), StatCan Table 17-10-0009-01 (quarterly estimates), as the previous
    module cached it.

    Returns columns `geo` (StatCan name, e.g. "Ontario"), `year` and `population`.
    """
    resource = files("canoe.residential").joinpath("data/statcan_17100009.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    # Quarterly estimates ("1946-01", "1946-04", ...): keep the January ones
    january = df.loc[df["REF_DATE"].str.endswith("-01") & df["VALUE"].notna()]
    return pd.DataFrame(
        {
            "geo": january["GEO"],
            "year": january["REF_DATE"].str.removesuffix("-01").astype(int),
            "population": january["VALUE"].astype(float),
        }
    ).reset_index(drop=True)


def get_statcan_population_projections() -> pd.DataFrame:
    """
    Projected population (July 1st) by geography, medium-growth scenario M1, all
    genders and ages, StatCan Table 17-10-0057-01.

    Reads `data/statcan_17100057_extract.csv`, the rows of the full table this
    function keeps (the full file is 154 MB); it filters as if it read the full
    table.

    Returns columns `geo`, `year` and `population` (persons).
    """
    resource = files("canoe.residential").joinpath("data/statcan_17100057_extract.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    rows = df.loc[
        (df["Projection scenario"] == "Projection scenario M1: medium-growth")
        & (df["Gender"] == "Total - gender")
        & (df["Age group"] == "All ages")
        & df["VALUE"].notna()
    ]
    return pd.DataFrame(
        {
            "geo": rows["GEO"],
            "year": rows["REF_DATE"].astype(int),
            # Published in thousands
            "population": rows["VALUE"].astype(float) * 1000,
        }
    ).reset_index(drop=True)


# ----------------------------------------------------------------------------
# NREL ResStock hourly profiles
# ----------------------------------------------------------------------------


def resstock_housing_types() -> dict[str, str]:
    """NRCan building type (CEUD table 14) -> ResStock housing type of its profiles."""
    return {
        "single detached": "single-family_detached",
        "single attached": "single-family_attached",
        "apartments": "multi-family_with_5plus_units",
        "mobile homes": "mobile_home",
    }


def get_resstock_consumption(
    cache_config: GoldConnectorConfig, us_state: str, housing_type: str
) -> pd.DataFrame:
    """
    Hourly energy use of an average household of a ResStock housing type in a US
    state (amy2018, upgrade 16), by end use (cached as `oedi_up16_<state>_<type>`).

    Returns one row per hour of the year (index 0-8759, from January 1st 00:00) and
    one column per `ResidentialEndUse`, in kBtu (space and water heating, space
    cooling) or kWh (the rest) per household.

    As the previous module, each hour takes the 15-minute value at the start of the
    hour (the series is 15-minutely, ending at 2019-01-01 00:00, which is hour 0),
    rather than the sum over the hour; negative values are set to 0.
    """
    # Columns summed into the profile of each end use: the energy delivered (kBtu)
    # for space and water heating and cooling, the energy used (kWh) otherwise
    end_use_columns: dict[ResidentialEndUse, list[str]] = {
        ResidentialEndUse.SpaceHeating: ["out.load.heating.energy_delivered.kbtu"],
        ResidentialEndUse.SpaceCooling: ["out.load.cooling.energy_delivered.kbtu"],
        ResidentialEndUse.WaterHeating: ["out.load.hot_water.energy_delivered.kbtu"],
        ResidentialEndUse.Lighting: [
            "out.electricity.lighting_exterior.energy_consumption.kwh",
            "out.electricity.lighting_garage.energy_consumption.kwh",
            "out.electricity.lighting_interior.energy_consumption.kwh",
            "out.natural_gas.lighting.energy_consumption.kwh",
        ],
        ResidentialEndUse.Refrigerators: [
            "out.electricity.refrigerator.energy_consumption.kwh"
        ],
        ResidentialEndUse.Freezers: ["out.electricity.freezer.energy_consumption.kwh"],
        ResidentialEndUse.DishWashers: [
            "out.electricity.dishwasher.energy_consumption.kwh"
        ],
        ResidentialEndUse.ClothesWashers: [
            "out.electricity.clothes_washer.energy_consumption.kwh"
        ],
        ResidentialEndUse.ClothesDryers: [
            "out.electricity.clothes_dryer.energy_consumption.kwh",
            "out.natural_gas.clothes_dryer.energy_consumption.kwh",
            "out.propane.clothes_dryer.energy_consumption.kwh",
        ],
        ResidentialEndUse.CookingRanges: [
            "out.electricity.range_oven.energy_consumption.kwh",
            "out.natural_gas.grill.energy_consumption.kwh",
            "out.natural_gas.range_oven.energy_consumption.kwh",
            "out.propane.range_oven.energy_consumption.kwh",
        ],
        ResidentialEndUse.OtherAppliances: [
            "out.electricity.plug_loads.energy_consumption.kwh"
        ],
    }
    dataset = f"oedi_up16_{us_state}_{housing_type}"
    cache_path = cache_config.cache_dir / Path("silver") / cache_config.cache_date
    file_path = cache_path / dataset / f"{dataset}_{cache_config.cache_date}.parquet"
    logger.debug(f"Loading cached ResStock table {dataset}")
    df = pd.read_parquet(file_path)
    if len(df) != 4 * 8760:
        raise ValueError(
            f"{dataset}: expected {4 * 8760} 15-minute rows, got {len(df)}"
        )
    missing = [c for cols in end_use_columns.values() for c in cols if c not in df]
    if missing:
        raise ValueError(f"{dataset}: columns {missing} not found")

    hourly = df.iloc[[len(df) - 1, *range(3, len(df) - 1, 4)]]
    households = float(df["units_represented"].iloc[0])
    return pd.DataFrame(
        {
            end_use: hourly[columns].astype(float).clip(lower=0).sum(axis=1).to_numpy()
            / households
            for end_use, columns in end_use_columns.items()
        }
    )

"""
Loaders for the datasets used by the electricity module.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, columns, labels, units), so when a source changes shape the error
points to the function to fix. They return tidy frames in the source's own units and
currency; conversions belong to the parameter modules.

Sources not usable from the data lake cache yet are read from `data/`, copied from
the previous module (see `DATA_LAKE_REQUESTS.md`):

- `data/coders_ca_system_parameters.csv`: CODERS `CA_system_parameters` as the
  previous module cached it (system line losses, reserve requirements).
- `data/aeo_transmission_distribution_costs.csv`: EIA AEO2025 transmission and
  distribution costs.

Weather data, 2018 only (the reference weather year; the cache has other years or
lacks them). Gzipped, read in memory. To move to the cache, then update
`source_years`:

- `data/ieso_gen_output_by_fuel_hourly_2018.xml.gz`: IESO hourly output by fuel.
- `data/ieso_goc_{output,capability}_2018.csv.gz`: IESO output and capability by
  generator; `data/ieso_hydro_types.csv` types the hydro generators.
- `data/statcan_25100015_hydro_2018.csv`: StatCan monthly hydro generation.
- `data/renewables_ninja_{solar,wind_onshore}_2018.csv.gz`: renewables.ninja
  profiles at each CODERS facility.

The new wind and solar bins are read from `<cache_dir>/renewables/`, finished rows of
an earlier database that cannot be rebuilt (the bin data behind them is not
available); their loaders undo a currency conversion, so they return source data.
"""

import gzip
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince, GoldConnectorConfig

from .catalogue import GenerationTechnology, GridLevel


@dataclass(frozen=True)
class SourceCosts:
    """
    Costs of one source, in `currency` of `currency_year` per `units`.

    Parameters
    ----------
    costs : pd.DataFrame
        One row per cost, the columns of each loader plus `cost`.
    currency : str
        Currency of the costs (a column of the exchange table, e.g. `USD`).
    currency_year : int
        Year of the currency (real dollars of that year).
    units : str
        Units of the costs, e.g. `c/kWh`.
    reference : str
        The source, for notes.
    """

    costs: pd.DataFrame
    currency: str
    currency_year: int
    units: str
    reference: str


def get_coders_system_line_losses() -> pd.DataFrame:
    """
    Losses of the provincial grids, transmission and distribution, as a fraction of
    the electricity sent out (CODERS `CA_system_parameters`,
    `system_line_losses_percent`, a fraction despite its name).

    Returns columns `region` (`CANOEProvince`) and `line_losses`.
    """
    resource = files("canoe.electricity").joinpath(
        "data/coders_ca_system_parameters.csv"
    )
    with resource.open("rb") as f:
        df = pd.read_csv(f, encoding="utf-8-sig")
    return pd.DataFrame(
        {
            "region": _coders_provinces(df, "province", "CA_system_parameters"),
            "line_losses": df["system_line_losses_percent"].astype(float),
        }
    )


def get_aeo_transmission_distribution_costs() -> SourceCosts:
    """
    Projected cost of transmission and of distribution of electricity, US average
    (EIA Annual Energy Outlook 2025, Table 8 'Electricity Supply, Disposition,
    Prices, and Emissions', reference case), in 2024 USD cents per kWh delivered.

    Costs columns `level` (`GridLevel`), `year` and `cost`.
    """
    resource = files("canoe.electricity").joinpath(
        "data/aeo_transmission_distribution_costs.csv"
    )
    with resource.open("rb") as f:
        df = pd.read_csv(f, encoding="utf-8-sig", index_col=0)
    levels = {
        "transmission": GridLevel.Transmission,
        "distribution": GridLevel.Distribution,
    }
    missing = sorted(set(levels) - set(df.index))
    if missing:
        raise ValueError(f"EIA AEO T&D costs: rows {missing} are missing")
    long = df.loc[list(levels)].rename_axis("label").reset_index()
    long = long.melt(id_vars="label", var_name="year", value_name="cost")
    return SourceCosts(
        costs=pd.DataFrame(
            {
                "level": long["label"].map(levels),
                "year": long["year"].astype(int),
                "cost": long["cost"].astype(float),
            }
        ),
        currency="USD",
        currency_year=2024,
        units="c/kWh",
        reference="EIA, Annual Energy Outlook 2025, reference case, Table 8",
    )


def get_coders_generators(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    Generating units in Canada (CODERS `generators`), one row per unit.

    Returns columns `region` (`CANOEProvince`, the operating region), `coders_type`
    (`gen_type`, lowercase), `facility` (facility name), `facility_code`, `capacity`
    (installed, MW), `annual_energy` (average annual output, GWh),
    `capacity_factor` (average), `start_year` and `renewal_year` (last renewal, the
    start year if never renewed).
    """
    file_path = _cache_file(cache_config, "coders_generators")
    logger.debug(f"Loading cached CODERS generators from {file_path}")
    df = pd.read_parquet(file_path)
    return pd.DataFrame(
        {
            "region": _coders_provinces(df, "operating_region", "generators"),
            "coders_type": df["gen_type"].str.lower(),
            "facility": df["generation_facility_name"],
            "facility_code": df["generation_facility_code"],
            "capacity": df["unit_installed_capacity"].astype(float),
            "annual_energy": df["unit_average_annual_energy"].astype(float),
            "capacity_factor": df["capacity_factor"].astype(float),
            "start_year": df["start_year"].astype(int),
            "renewal_year": df["previous_renewal_year"].astype(int),
        }
    )


def get_coders_storage(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    Storage facilities in Canada (CODERS `storage`), one row per facility.

    Returns columns `region` (`CANOEProvince`, the operating region), `coders_type`
    (`storage_type`, lowercase), `facility` (name), `capacity` (MW), `duration`
    (hours at full power), `start_year` and `renewal_year` (last renewal, the start
    year if never renewed).
    """
    file_path = _cache_file(cache_config, "coders_storage")
    logger.debug(f"Loading cached CODERS storage from {file_path}")
    df = pd.read_parquet(file_path)
    return pd.DataFrame(
        {
            "region": _coders_provinces(df, "operating_region", "storage"),
            "coders_type": df["storage_type"].str.lower(),
            "facility": df["storage_facility_name"],
            "capacity": df["storage_capacity"].astype(float),
            "duration": df["storage_duration"].astype(float),
            "start_year": df["start_year"].astype(int),
            "renewal_year": df["previous_renewal_year"].astype(int),
        }
    )


def get_coders_generation_generic(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    Generic parameters of each type of generator (CODERS `generation_generic`), in
    the CAD of `source_years.coders_currency` (the table gives no year).

    Returns one row per type, indexed by `coders_type` (`gen_type`, lowercase), with
    columns `service_life` (years), `efficiency` (fraction, NaN where none),
    `fixed_om` (CAD/MW-year) and `variable_om` (CAD/MWh).
    """
    file_path = _cache_file(cache_config, "coders_generation_generic")
    logger.debug(f"Loading cached CODERS generation_generic from {file_path}")
    df = pd.read_parquet(file_path)
    return pd.DataFrame(
        {
            "service_life": df["service_life"].astype(int).to_numpy(),
            "efficiency": df["efficiency"].astype(float).to_numpy(),
            "fixed_om": df["fixed_om_costs"].astype(float).to_numpy(),
            "variable_om": df["variable_om_costs"].astype(float).to_numpy(),
        },
        index=pd.Index(df["gen_type"].str.lower(), name="coders_type"),
    )


def get_atb_generation(
    cache_config: GoldConnectorConfig, display_names: list[str], scenario: str
) -> pd.DataFrame:
    """
    Heat rate, overnight capital cost and operation and maintenance costs of NREL
    ATB 2024 technologies, market case (`core_metric_case = Market`), in USD of
    `source_years.atb_currency`. The 20-year cost recovery period is taken; these
    parameters do not depend on it.

    Parameters
    ----------
    display_names : list[str]
        ATB technologies (`display_name`), see
        `GenerationTechnology.get_atb_display_name`.
    scenario : str
        ATB scenario (`Moderate`, `Advanced` or `Conservative`).

    Returns
    -------
    pd.DataFrame
        Columns `display_name`, `parameter` (`Heat Rate` in MMBtu/MWh, `OCC` in
        $/kW, `Fixed O&M` in $/kW-year, `Variable O&M` in $/MWh; for CCS
        retrofits `Net Output Penalty`, a fraction, and `Additional OCC` in $/kW),
        `year` and `value`.

    Raises
    ------
    ValueError
        If a technology has no values, or more than one per parameter and year.
    """
    file_path = _cache_file(cache_config, "atb")
    logger.debug(f"Loading cached NREL ATB from {file_path}")
    df = pd.read_parquet(file_path)
    parameters = [
        "Heat Rate",
        "OCC",
        "Fixed O&M",
        "Variable O&M",
        "Net Output Penalty",
        "Additional OCC",
    ]
    selected = df.loc[
        df["display_name"].isin(display_names)
        & df["core_metric_parameter"].isin(parameters)
        & (df["scenario"] == scenario)
        & (df["core_metric_case"] == "Market")
        & (df["crpyears"] == "20")
    ]
    atb = pd.DataFrame(
        {
            "display_name": selected["display_name"],
            "parameter": selected["core_metric_parameter"],
            "year": selected["core_metric_variable"].astype(int),
            "value": selected["value"].astype(float),
        }
    ).reset_index(drop=True)

    missing = sorted(set(display_names) - set(atb["display_name"]))
    if missing:
        raise ValueError(f"NREL ATB: no {scenario} values for {missing}")
    duplicated = atb.duplicated(["display_name", "parameter", "year"])
    if duplicated.any():
        raise ValueError(
            f"NREL ATB: more than one value per year for\n{atb.loc[duplicated]}"
        )
    return atb


def get_vre_bin_investment_costs(cache_config: GoldConnectorConfig) -> SourceCosts:
    """
    Investment cost of the new wind and solar resource bins: NREL ATB 2023 overnight
    capital cost, at the end of each vintage's period, of the bin's turbine class
    mix (wind) plus its spur line to the grid (Sutubra, 2024).

    The cached rows are finished Temoa rows (`renewables/cost_invest.parquet`)
    converted from USD with a flat 1.30 (see `ELECTRICITY_MODULE_BUGS.md`, entry 2);
    the conversion is undone here, so the costs are in 2021 USD, the ATB 2023 dollars.

    Returns
    -------
    SourceCosts
        Columns `region`, `technology` (`GenerationTechnology`), `bin` (1 is the
        cheapest), `vintage` and `cost` ($/kW).
    """
    # Flat USD to CAD factor of the cached costs, found against NREL ATB 2023
    USD_TO_CAD = 1.30

    df = _read_vre_bins(cache_config, "cost_invest", "tech")
    return SourceCosts(
        costs=pd.DataFrame(
            {
                **_vre_bin_columns(df, "tech"),
                "vintage": df["vintage"].astype(int),
                "cost": df["cost"].astype(float) / USD_TO_CAD,
            }
        ),
        currency="USD",
        currency_year=2021,
        units="$/kW",
        reference="NREL ATB 2023 OCC by turbine class mix plus spur line costs "
        + "(Sutubra, 2024)",
    )


def get_vre_bin_fixed_costs(cache_config: GoldConnectorConfig) -> SourceCosts:
    """
    Fixed operation and maintenance cost of the new wind and solar resource bins:
    NREL ATB 2023, at the end of each vintage's period, of the bin's turbine class mix
    (Sutubra, 2024). The same in every period a vintage lives.

    Converted back from the cached rows (`renewables/cost_fixed.parquet`) as
    `get_vre_bin_investment_costs`: 2021 USD.

    Returns
    -------
    SourceCosts
        Columns `region`, `technology`, `bin`, `vintage` and `cost` ($/kW-year).

    Raises
    ------
    ValueError
        If the cost of a vintage changes between periods.
    """
    # Flat USD to CAD factor of the cached costs, found against NREL ATB 2023
    USD_TO_CAD = 1.30

    df = _read_vre_bins(cache_config, "cost_fixed", "tech")
    costs = pd.DataFrame(
        {
            **_vre_bin_columns(df, "tech"),
            "vintage": df["vintage"].astype(int),
            "cost": df["cost"].astype(float) / USD_TO_CAD,
        }
    )
    keys = ["region", "technology", "bin", "vintage"]
    changing = costs.groupby(keys, sort=False)["cost"].nunique() > 1
    if changing.any():
        raise ValueError(
            "VRE bin fixed costs change between periods for\n"
            + f"{changing.loc[changing].index.tolist()}"
        )
    return SourceCosts(
        costs=costs.drop_duplicates(keys).reset_index(drop=True),
        currency="USD",
        currency_year=2021,
        units="$/kW-year",
        reference="NREL ATB 2023 Fixed O&M by turbine class mix (Sutubra, 2024)",
    )


def get_vre_bin_capacity_limits(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    Largest capacity of each new wind and solar resource bin (Sutubra, 2024; grid
    cells binned by ascending LCOE), from `renewables/max_capacity.parquet`.

    Returns columns `region`, `technology`, `bin`, `period` and `capacity` (GW).
    """
    df = _read_vre_bins(cache_config, "max_capacity", "tech_or_group")
    if set(df["operator"]) != {"le"}:
        raise ValueError(
            f"VRE bin capacity limits: operators {set(df['operator'])}, expected 'le'"
        )
    return pd.DataFrame(
        {
            **_vre_bin_columns(df, "tech_or_group"),
            "period": df["period"].astype(int),
            "capacity": df["capacity"].astype(float),
        }
    ).reset_index(drop=True)


def get_vre_bin_capacity_factors(cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    Hourly capacity factor of the new wind and solar resource bins by vintage
    (Sutubra, 2024, 2018 weather; indexed to NREL ATB 2023 by construction year), from
    `renewables/capacity_factor.parquet`.

    The cached rows leave out the hours with a capacity factor of 0, and repeat some
    rows (see `ELECTRICITY_MODULE_BUGS.md`, entry 1): the repeats are dropped and the
    missing hours are completed with 0, so every (region, bin, vintage) has its 8760
    hours.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `bin`, `vintage`, `hour` (0-8759, EST) and
        `factor`.

    Raises
    ------
    ValueError
        If a repeated row has a different capacity factor.
    """
    HOURS = 8760

    df = _read_vre_bins(
        cache_config,
        "capacity_factor",
        "tech",
        ["region", "season", "tod", "tech", "vintage", "factor"],
    )
    keys = ["region", "season", "tod", "tech", "vintage"]
    df = df.drop_duplicates()
    conflicting = df.duplicated(keys)
    if conflicting.any():
        raise ValueError(
            "VRE bin capacity factors: repeated hours with different values\n"
            + f"{df.loc[conflicting].head()}"
        )
    # Hour of the year from the day (D001-D365) and hour of the day (H01-H24)
    hour = (
        (df["season"].str[1:].astype(int) - 1) * 24 + df["tod"].str[1:].astype(int) - 1
    )

    # Every (region, bin, vintage) at every hour, 0 where the cache has no row
    groups = df[["region", "tech", "vintage"]].drop_duplicates().reset_index(drop=True)
    group_of_row = (
        df[["region", "tech", "vintage"]]
        .merge(groups.reset_index(), on=["region", "tech", "vintage"], how="left")[
            "index"
        ]
        .to_numpy()
    )
    factors = np.zeros((len(groups), HOURS))
    factors[group_of_row, hour.to_numpy()] = df["factor"].astype(float).to_numpy()

    # Labels parsed once per (region, bin, vintage), then repeated for its hours;
    # object arrays keep the enums (pandas would turn them into strings)
    labels = _vre_bin_columns(pd.DataFrame(groups), "tech")
    return pd.DataFrame(
        {
            "region": np.repeat(labels["region"].to_numpy(dtype=object), HOURS),
            "technology": np.repeat(labels["technology"].to_numpy(dtype=object), HOURS),
            "bin": np.repeat(np.asarray(labels["bin"], dtype=int), HOURS),
            "vintage": np.repeat(groups["vintage"].to_numpy(dtype=int), HOURS),
            "hour": np.tile(np.arange(HOURS), len(groups)),
            "factor": factors.ravel(),
        }
    )


def get_ieso_output_by_fuel(year: int) -> pd.DataFrame:
    """
    Hourly output of the Ontario grid by fuel (IESO, Generator Output by Fuel Type
    Hourly Report, `PUB_GenOutputbyFuelHourly_<year>.xml`), market participants over
    20 MW.

    TODO: only 2018 is available, from `data/` (see `DATA_LAKE_REQUESTS.md`); the
    cache has 2025. Move to the cache and update `source_years.ieso_hourly`.

    Parameters
    ----------
    year : int
        Year of the report.

    Returns
    -------
    pd.DataFrame
        Columns `hour` (0-8759, EST), `fuel` (e.g. `WIND`, `SOLAR`) and `output`
        (MWh).

    Raises
    ------
    ValueError
        If the year is not available, or the report is not for that year.
    """
    _check_stand_in_year("IESO hourly output by fuel", year, 2018)
    resource = files("canoe.electricity").joinpath(
        f"data/ieso_gen_output_by_fuel_hourly_{year}.xml.gz"
    )
    with resource.open("rb") as f, gzip.open(f) as xml:
        root = ElementTree.parse(xml).getroot()
    ns = {"ieso": "http://www.ieso.ca/schema"}
    delivery_year = root.findtext("ieso:DocBody/ieso:DeliveryYear", namespaces=ns)
    if delivery_year != str(year):
        raise ValueError(f"IESO output by fuel: report for {delivery_year}, not {year}")

    rows: list[tuple[int, str, float]] = []
    for day, daily in enumerate(root.iterfind("ieso:DocBody/ieso:DailyData", ns)):
        for hourly in daily.iterfind("ieso:HourlyData", ns):
            # Hours are numbered 1-24 (hour ending)
            hour = day * 24 + int(hourly.findtext("ieso:Hour", namespaces=ns) or 0) - 1
            for total in hourly.iterfind("ieso:FuelTotal", ns):
                output = total.findtext("ieso:EnergyValue/ieso:Output", namespaces=ns)
                rows.append(
                    (
                        hour,
                        total.findtext("ieso:Fuel", namespaces=ns) or "",
                        float(output) if output else np.nan,
                    )
                )
    return pd.DataFrame(rows, columns=["hour", "fuel", "output"])


def get_ieso_generator_output(year: int) -> pd.DataFrame:
    """
    Hourly output and available capacity of each Ontario generator over 20 MW (IESO,
    Generator Output and Capability, `GOC-<year>.xlsx`, sheets `Output` and
    `Available Capacities`).

    TODO: only 2018 is available, from `data/` (see `DATA_LAKE_REQUESTS.md`); the
    cache has the 2025 monthly reports. Move to the cache and update
    `source_years.ieso_hourly`.

    Parameters
    ----------
    year : int
        Year of the data.

    Returns
    -------
    pd.DataFrame
        Columns `hour` (0-8759, EST), `generator` (IESO name), `output` and
        `capability` (MW).

    Raises
    ------
    ValueError
        If the year is not available, or the data is not a full year.
    """
    _check_stand_in_year("IESO generator output and capability", year, 2018)
    tables: dict[str, pd.DataFrame] = {}
    for measure, name in (("output", "output"), ("capability", "capability")):
        resource = files("canoe.electricity").joinpath(
            f"data/ieso_goc_{name}_{year}.csv.gz"
        )
        with resource.open("rb") as f:
            df = pd.read_csv(f, compression="gzip")
        if set(pd.to_datetime(df["Date"]).dt.year) != {year} or len(df) != 8760:
            raise ValueError(f"IESO generator {measure}: not the 8760 hours of {year}")
        df = df.drop(columns=["TOTAL"], errors="ignore")
        df.index = pd.RangeIndex(len(df), name="hour")
        tables[measure] = (
            df.drop(columns=["Date", "Hour"])
            .apply(pd.to_numeric, errors="coerce")
            .melt(ignore_index=False, var_name="generator", value_name=measure)
            .reset_index()
        )
    return tables["output"].merge(
        tables["capability"], on=["hour", "generator"], how="inner"
    )


def get_ieso_hydro_types() -> pd.DataFrame:
    """
    Type of each Ontario hydro generator in the IESO data (`data/ieso_hydro_types.csv`,
    from the previous module).

    Returns columns `generator` (IESO name) and `technology` (`GenerationTechnology`,
    run-of-river or daily reservoir).
    """
    resource = files("canoe.electricity").joinpath("data/ieso_hydro_types.csv")
    with resource.open("rb") as f:
        df = pd.read_csv(f, encoding="utf-8-sig")
    technologies = {
        "hydro_run": GenerationTechnology.HydroRunOfRiver,
        "hydro_daily": GenerationTechnology.HydroDaily,
    }
    unknown = sorted(set(df["hydro_type"]) - set(technologies))
    if unknown:
        raise ValueError(f"IESO hydro types: unknown types {unknown}")
    return pd.DataFrame(
        {
            "generator": df["ieso_gen"],
            "technology": [technologies[t] for t in df["hydro_type"]],
        }
    )


def get_statcan_monthly_hydro(year: int) -> pd.DataFrame:
    """
    Monthly generation of hydraulic turbines by province, all classes of producers
    (StatCan Table 25-10-0015-01).

    TODO: only 2018 is available, from `data/` (the previous module's extract, see
    `DATA_LAKE_REQUESTS.md`); the table is not in the cache. Move to the cache and
    update `source_years.statcan_monthly_hydro`.

    Parameters
    ----------
    year : int
        Year of the data.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `month` (1-12) and `generation` (MWh).

    Raises
    ------
    ValueError
        If the year is not available, or a province lacks a month.
    """
    _check_stand_in_year("StatCan 25-10-0015-01", year, 2018)
    resource = files("canoe.electricity").joinpath(
        f"data/statcan_25100015_hydro_{year}.csv"
    )
    with resource.open("rb") as f:
        df = pd.read_csv(f, index_col=0)
    df = df.loc[
        (df["Type of electricity generation"] == "Hydraulic turbine")
        & (
            df["Class of electricity producer"]
            == "Total all classes of electricity producer"
        )
    ]
    dates = df["REF_DATE"].str.split("-", expand=True).astype(int)
    df = df.loc[dates[0] == year]
    monthly = pd.DataFrame(
        {
            "region": _coders_provinces(df, "GEO", "StatCan 25-10-0015-01"),
            "month": dates.loc[df.index, 1],
            "generation": df["VALUE"].astype(float),
        }
    ).reset_index(drop=True)
    incomplete = monthly.groupby("region")["month"].nunique() != 12
    if incomplete.any():
        raise ValueError(
            "StatCan 25-10-0015-01: provinces without 12 months "
            + f"{incomplete.loc[incomplete].index.tolist()}"
        )
    return monthly


def get_renewables_ninja_facility_profiles(year: int) -> pd.DataFrame:
    """
    Hourly capacity factor at the location of each CODERS wind and solar facility
    (renewables.ninja: solar PV tilted 45°, MERRA-2; onshore wind Vestas V112 3 MW at
    110 m), as the previous module downloaded them.

    TODO: only 2018 is available, from `data/` (see `DATA_LAKE_REQUESTS.md`); the
    cache has 2022 by coordinates. Move to the cache and update
    `source_years.renewables_ninja`.

    Parameters
    ----------
    year : int
        Weather year.

    Returns
    -------
    pd.DataFrame
        One column per facility (`facility_code`), indexed by `hour` (0-8759, EST);
        missing values are 0.

    Raises
    ------
    ValueError
        If the year is not available, or a file is not the 8760 hours of that year.
    """
    _check_stand_in_year("renewables.ninja", year, 2018)
    profiles: list[pd.DataFrame] = []
    for technology in ("solar", "wind_onshore"):
        resource = files("canoe.electricity").joinpath(
            f"data/renewables_ninja_{technology}_{year}.csv.gz"
        )
        with resource.open("rb") as f:
            df = pd.read_csv(f, compression="gzip", index_col=0)
        timestamps = pd.Series(pd.to_datetime(df.index, utc=True).tz_convert("EST"))
        if len(df) != 8760 or set(timestamps.dt.year) != {year}:
            raise ValueError(f"renewables.ninja {technology}: not the hours of {year}")
        df.index = pd.RangeIndex(len(df), name="hour")
        profiles.append(df.astype(float).fillna(0.0))
    return pd.concat(profiles, axis=1)


def _check_stand_in_year(source: str, year: int, available: int):
    """Raise if `year` of a source copied into `data/` is not the one available"""
    if year != available:
        raise ValueError(
            f"{source}: only {available} is available (copied into data/, see "
            + f"DATA_LAKE_REQUESTS.md), not {year}"
        )


def _read_vre_bins(
    cache_config: GoldConnectorConfig,
    table: str,
    tech_column: str,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    One table of the new wind and solar bins: finished Temoa rows of the data set
    version 001, extracted from an earlier CANOE database (not rebuildable).
    `columns` (all by default) are read, plus `data_id`.
    """
    file_path = cache_config.cache_dir / "renewables" / f"{table}.parquet"
    logger.debug(f"Loading cached VRE bins from {file_path}")
    df = pd.read_parquet(
        file_path, columns=None if columns is None else [*columns, "data_id"]
    )
    # The fingerprint of the extraction the corrections here were checked against
    # Checked on the distinct values: the capacity factors have 19M rows
    versions = {str(code)[-3:] for code in df["data_id"].unique()}
    if versions != {"001"}:
        raise ValueError(
            f"VRE bins {table}: data set versions {versions}, expected 001. The "
            + "source changed: check the USD to CAD factor in the loaders"
        )
    names = pd.Series(df[tech_column].unique())
    if not names.str.fullmatch(r"E_(WND_ON|SOL_PV)-NEW-\d+").all():
        raise ValueError(f"VRE bins {table}: unexpected technology names")
    return df.drop(columns="data_id")


def _vre_bin_columns(df: pd.DataFrame, tech_column: str) -> dict[str, pd.Series]:
    """`region`, `technology` and `bin` of the bin rows (e.g. `E_WND_ON-NEW-3`)"""
    technologies = {
        t.get_tech_code(): t for t in GenerationTechnology if t.is_resource_binned()
    }
    parts = df[tech_column].str.extract(r"^(?P<code>.+)-NEW-(?P<bin>\d+)$")
    return {
        "region": pd.Series(df["region"].map(CANOEProvince)),
        "technology": pd.Series(parts["code"].map(technologies)),
        "bin": pd.Series(parts["bin"].astype(int)),
    }


def _cache_file(cache_config: GoldConnectorConfig, dataset: str) -> Path:
    """Parquet file of `dataset` in the cache snapshot"""
    return (
        cache_config.cache_dir
        / "silver"
        / cache_config.cache_date
        / dataset
        / f"{dataset}_{cache_config.cache_date}.parquet"
    )


def _coders_provinces(df: pd.DataFrame, column: str, table: str) -> pd.Series:
    """The full province names of `column` of a CODERS table as `CANOEProvince`"""
    provinces = df[column].str.replace("Québec", "Quebec")
    unknown = sorted(set(provinces) - {p.value for p in CANOEProvince})
    if unknown:
        raise ValueError(f"CODERS {table}: unknown provinces {unknown}")
    return provinces.map(CANOEProvince)

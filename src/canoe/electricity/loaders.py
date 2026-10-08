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

The new wind and solar bins are read from `<cache_dir>/renewables/`, finished rows of
an earlier database that cannot be rebuilt (the bin data behind them is not
available); their loaders undo a currency conversion, so they return source data.
"""

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

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
    (`gen_type`, lowercase), `facility` (facility name), `capacity` (installed, MW),
    `annual_energy` (average annual output, GWh), `start_year` and `renewal_year`
    (last renewal, the start year if never renewed).
    """
    file_path = _cache_file(cache_config, "coders_generators")
    logger.debug(f"Loading cached CODERS generators from {file_path}")
    df = pd.read_parquet(file_path)
    return pd.DataFrame(
        {
            "region": _coders_provinces(df, "operating_region", "generators"),
            "coders_type": df["gen_type"].str.lower(),
            "facility": df["generation_facility_name"],
            "capacity": df["unit_installed_capacity"].astype(float),
            "annual_energy": df["unit_average_annual_energy"].astype(float),
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
        $/kW, `Fixed O&M` in $/kW-year, `Variable O&M` in $/MWh), `year` and
        `value`.

    Raises
    ------
    ValueError
        If a technology has no values, or more than one per parameter and year.
    """
    file_path = _cache_file(cache_config, "atb")
    logger.debug(f"Loading cached NREL ATB from {file_path}")
    df = pd.read_parquet(file_path)
    parameters = ["Heat Rate", "OCC", "Fixed O&M", "Variable O&M"]
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


def _read_vre_bins(
    cache_config: GoldConnectorConfig, table: str, tech_column: str
) -> pd.DataFrame:
    """
    One table of the new wind and solar bins: finished Temoa rows of the data set
    version 001, extracted from an earlier CANOE database (not rebuildable).
    """
    file_path = cache_config.cache_dir / "renewables" / f"{table}.parquet"
    logger.debug(f"Loading cached VRE bins from {file_path}")
    df = pd.read_parquet(file_path)
    # The fingerprint of the extraction the corrections here were checked against
    versions = set(df["data_id"].str[-3:])
    if versions != {"001"}:
        raise ValueError(
            f"VRE bins {table}: data set versions {versions}, expected 001. The "
            + "source changed: check the USD to CAD factor in the loaders"
        )
    if not df[tech_column].str.fullmatch(r"E_(WND_ON|SOL_PV)-NEW-\d+").all():
        raise ValueError(f"VRE bins {table}: unexpected technology names")
    return df


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

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
"""

from dataclasses import dataclass
from importlib.resources import files

import pandas as pd

from canoe.common import CANOEProvince

from .catalogue import GridLevel


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
    # Full province names, Quebec with its accent
    provinces = df["province"].str.replace("Québec", "Quebec")
    unknown = sorted(set(provinces) - {p.value for p in CANOEProvince})
    if unknown:
        raise ValueError(f"CODERS CA_system_parameters: unknown provinces {unknown}")
    return pd.DataFrame(
        {
            "region": provinces.map(CANOEProvince),
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

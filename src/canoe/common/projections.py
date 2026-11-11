"""
Projected GDP and population, the series that grow the sectors' base-year demands.

The sources are chosen once in the base configuration (`gdp` and `population` of
`CANOEBaseConfig`) and inherited by the sectors, so all demands grow consistently.
Every source gives a **series table**, the format a user's file must have (see
`read_series_table`): one row per year with columns

- `region`: a `CANOEProvince`, or `None` for Canada as a whole (national).
- `year`, `value`: the level of the series that year (GDP in constant dollars,
  persons, ...). Only its growth is used, so the units don't matter, but they must
  be the same within a series.
- `source`: description, for notes.

`growth_by_period` turns a table into the growth of each province from the year of
a sector's base data to each model period. A province with rows of its own takes
them; one without takes the national rows. The two are never mixed: a province's
growth comes from a single series.
"""

import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from .cache_connector import GoldConnectorConfig
from .labels import normalize_label
from .loaders import (
    get_cer_gdp,
    get_statcan_population_estimates,
    get_statcan_population_projections,
)
from .periods import period_end_years
from .provinces import CANOEProvince


class CERScenario(StrEnum):
    """
    Scenario of the CER Canada's Energy Future 2023 macro indicators.

    Values are the scenario names as they appear in the CER data.
    """

    GlobalNetZero = "Global Net-zero"
    """Canada and the rest of the world reach net-zero emissions by 2050."""

    CanadaNetZero = "Canada Net-zero"
    """Canada reaches net-zero emissions by 2050; the rest of the world acts less."""

    CurrentMeasures = "Current Measures"
    """Only climate policies in place today, no further action."""


class DemandProjectionPoint(StrEnum):
    """
    Year of each model period at which a projected series (GDP, population, a demand
    forecast) scales the base-year demands.

    See `canoe.common.periods` for the years a period covers.
    """

    PeriodEnd = "period_end"
    """The series at the end of the period (the next label in `future_periods`, or the
    end of the horizon for the last period), relative to the year of the base demand
    data."""

    PeriodStart = "period_start"
    """The series at the label year of the period (the year just before it starts),
    relative to the year of the base demand data."""

    Legacy = "legacy"
    """The series at the label year of the period relative to the first model period,
    so the first period keeps the base-year demand unchanged. Reproduces the previous
    agriculture module; to be removed."""


class CERGDPSource(BaseModel):
    """Real GDP of Canada, CER Canada's Energy Future 2023 macro indicators
    (national)."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["cer"] = "cer"
    scenario: CERScenario = CERScenario.GlobalNetZero
    """CER scenario."""


class StatCanPopulationSource(BaseModel):
    """Population of each province, StatCan estimates (Table 17-10-0009-01) and
    projections (Table 17-10-0057-01, medium-growth scenario M1)."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["statcan"] = "statcan"


class CSVSeriesSource(BaseModel):
    """A series file in the format of `read_series_table`."""

    model_config = ConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        extra="forbid", frozen=True, use_attribute_docstrings=True
    )
    source: Literal["csv"] = "csv"
    path: Path
    """CSV file of the series, relative to the directory the pipeline runs from."""


GDPSource = Annotated[CERGDPSource | CSVSeriesSource, Field(discriminator="source")]
PopulationSource = Annotated[
    StatCanPopulationSource | CSVSeriesSource, Field(discriminator="source")
]


class RejectsDeprecatedProjectionFields(BaseModel):
    """
    Mixin of the configs that used to take `gdp_scenario` and `gdp_projection_point`:
    the fields are still accepted by name, but setting them fails with what replaced
    them.
    """

    gdp_scenario: None = None
    """Removed: set the scenario of the CER GDP source, `gdp = { source = "cer",
    scenario = "Global Net-zero" }` in `[compiler.base]`."""

    gdp_projection_point: None = None
    """Removed: renamed `demand_projection_point`."""

    @field_validator("gdp_scenario", "gdp_projection_point", mode="before")
    @classmethod
    def _reject_deprecated(cls, value: object, info: ValidationInfo) -> None:
        replacement = {
            "gdp_scenario": "set the scenario of the CER GDP source in "
            + '[compiler.base], e.g. gdp = { source = "cer", scenario = '
            + f'"{value}" }}',
            "gdp_projection_point": "it was renamed demand_projection_point",
        }[str(info.field_name)]
        raise ValueError(f"{info.field_name} is no longer used: {replacement}")


def _series_table(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["region", "year", "value", "source"])


def get_gdp_table(source: GDPSource, cache_config: GoldConnectorConfig) -> pd.DataFrame:
    """
    The series table of the GDP `source` (see the module docstring), checked by
    `check_series_table`.
    """
    match source:
        case CERGDPSource(scenario=scenario):
            gdp = get_cer_gdp(cache_config, scenario.value)
            description = f"CER Canada's Energy Future 2023, real GDP of Canada ({scenario.value})"
            table = _series_table(
                [
                    {
                        "region": None,
                        "year": int(year),
                        "value": float(value),
                        "source": description,
                    }
                    for year, value in zip(gdp["year"], gdp["gdp"])
                ]
            )
            name = "CER GDP"
        case CSVSeriesSource(path=path):
            table = read_series_table(path)
            name = str(path)
    check_series_table(table, name)
    return table


def get_population_table(
    source: PopulationSource, provinces: list[CANOEProvince]
) -> pd.DataFrame:
    """
    The series table of the population `source` (see the module docstring), checked
    by `check_series_table`. StatCan sources give the rows of `provinces`.
    """
    match source:
        case StatCanPopulationSource():
            table = statcan_population_table(
                get_statcan_population_estimates(),
                get_statcan_population_projections(),
                provinces,
            )
            name = "StatCan population"
        case CSVSeriesSource(path=path):
            table = read_series_table(path)
            name = str(path)
    check_series_table(table, name)
    return table


def statcan_population_table(
    estimates: pd.DataFrame,
    projections: pd.DataFrame,
    provinces: list[CANOEProvince],
) -> pd.DataFrame:
    """
    Series table of the population of each of `provinces`, as the previous
    residential module put it together: the estimates (January 1st) up to their last
    year, then the province's projections (July 1st) after it, then, beyond the last
    projected year of the province, Canada's projected growth applied to the
    province.

    params:
    - estimates, projections: columns `geo` (StatCan name, "Canada" included),
      `year`, `population`; see `canoe.common.loaders.get_statcan_population_estimates`
      and `get_statcan_population_projections`

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> estimates = pd.DataFrame({"geo": "Ontario", "year": [2023, 2024], "population": [10.0, 11.0]})
    >>> projections = pd.DataFrame(
    ...     {
    ...         "geo": ["Ontario"] * 3 + ["Canada"] * 2,
    ...         "year": [2024, 2025, 2026, 2026, 2027],
    ...         "population": [10.5, 12.0, 13.0, 40.0, 44.0],
    ...     }
    ... )
    >>> table = statcan_population_table(estimates, projections, [ON])
    >>> list(zip(table["year"], table["value"].round(2)))
    [(2023, 10.0), (2024, 11.0), (2025, 12.0), (2026, 13.0), (2027, 14.3)]
    """

    def series(df: pd.DataFrame, geo: str) -> pd.Series:
        """Population of `geo` by year"""
        rows = df.loc[df["geo"] == geo]
        return pd.Series(rows["population"].to_numpy(), index=rows["year"].to_numpy())

    description = (
        "StatCan population estimates (Table 17-10-0009-01) and projections (Table "
        + "17-10-0057-01, M1), extended with Canada's projected growth"
    )
    canada = series(projections, "Canada")
    rows: list[dict[str, object]] = []
    for province in provinces:
        estimated = series(estimates, province.value)
        projected = series(projections, province.value)
        projected = projected.loc[projected.index > estimated.index.max()]
        last_year = int(projected.index.max())
        # Beyond the province's projections: Canada's growth from that year on
        growth = float(projected.loc[last_year]) / float(canada.loc[last_year])
        extended = canada.loc[canada.index > last_year] * growth
        population = pd.concat([estimated, projected, extended])
        rows.extend(
            {
                "region": province,
                "year": int(year),
                "value": float(value),
                "source": description,
            }
            for year, value in zip(population.index, population.to_numpy())
        )
    return _series_table(rows)


def read_series_table(path: Path) -> pd.DataFrame:
    """
    The series table of a user's CSV file, with columns:

    - `region`: a province (code or name, see `CANOEProvince.from_str`), or empty,
      `Canada` or `CA` for Canada as a whole.
    - `year`, `value`: the level of the series that year, positive.
    - `source` (optional): description, for notes; the file name if absent or empty.

    National rows are logged as a warning: they apply to every province without rows
    of its own.

    Raises
    ------
    ValueError
        If a column is missing or unknown, or a value can't be read (every such row
        is listed).
    """
    REQUIRED = ["region", "year", "value"]
    NATIONAL = {"", "canada", "ca"}
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    unknown = [c for c in raw.columns if c not in [*REQUIRED, "source"]]
    if missing or unknown:
        raise ValueError(
            f"{path}: missing columns {missing}, unknown columns {unknown}; expected "
            + f"{REQUIRED} and optionally 'source'"
        )

    def number(text: str, column: str) -> float:
        if not text:
            raise ValueError(f"empty {column}")
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(f"{column} {text!r} is not a finite number")
        return value

    def year(text: str) -> int:
        value = number(text, "year")
        if not value.is_integer():
            raise ValueError(f"year {text!r} is not a whole number")
        return int(value)

    def positive(text: str) -> float:
        value = number(text, "value")
        if value <= 0:
            raise ValueError(f"value {text!r} is not positive")
        return value

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for line, row in enumerate(raw.to_dict("records"), start=2):
        values = {column: str(value).strip() for column, value in row.items()}
        try:
            rows.append(
                {
                    "region": None
                    if normalize_label(values["region"]) in NATIONAL
                    else CANOEProvince.from_str(values["region"]),
                    "year": year(values["year"]),
                    "value": positive(values["value"]),
                    "source": values.get("source") or path.name,
                }
            )
        except ValueError as error:
            errors.append(f"line {line}: {error}")
    if errors:
        raise ValueError(f"{path}: rows that can't be read:\n" + "\n".join(errors))

    national = sum(row["region"] is None for row in rows)
    if national:
        logger.warning(
            f"{path}: {national} national rows (no region, Canada or CA) apply to every "
            + "province without rows of its own"
        )
    return _series_table(rows)


def check_series_table(table: pd.DataFrame, name: str) -> None:
    """
    Check that `table` is a series table (see the module docstring): its columns,
    regions, positive values, and no (region, year) twice.

    Raises
    ------
    ValueError
        If it is not, naming the table and the rows at fault.
    """
    columns = list(_series_table([]).columns)
    if list(table.columns) != columns:
        raise ValueError(f"{name}: columns {list(table.columns)}, expected {columns}")
    bad = [
        not (
            (pd.isna(region) or isinstance(region, CANOEProvince))
            and isinstance(value, float)
            and math.isfinite(value)
            and value > 0
        )
        for region, value in zip(table["region"], table["value"])
    ]
    if any(bad):
        raise ValueError(f"{name}: rows with invalid regions or values:\n{table[bad]}")
    repeated = table.duplicated(["region", "year"], keep=False)
    if repeated.any():
        raise ValueError(
            f"{name}: years given twice:\n{table.loc[repeated, ['region', 'year']]}"
        )


def growth_by_period(
    table: pd.DataFrame,
    provinces: list[CANOEProvince],
    index_year: int,
    future_periods: list[int],
    period_step: int,
    projection_point: DemandProjectionPoint,
) -> pd.DataFrame:
    """
    Growth of the series of each of `provinces` from `index_year` (the year of the
    base demand data it scales) to each model period, read at `projection_point`: the
    province's own rows if `table` has any, the national rows otherwise.

    params:
    - table: series table, see the module docstring

    Returns region, period, growth, source (the series' source, for notes)

    Raises
    ------
    ValueError
        If a province has no series, or its series lacks `index_year` or a year read.

    Examples
    --------
    >>> ON, QC = CANOEProvince.ONTARIO, CANOEProvince.QUEBEC
    >>> table = _series_table(
    ...     [{"region": None, "year": y, "value": v, "source": "national"}
    ...      for y, v in [(2022, 10.0), (2030, 12.0), (2035, 15.0)]]
    ...     + [{"region": QC, "year": y, "value": v, "source": "Quebec"}
    ...        for y, v in [(2022, 4.0), (2030, 5.0), (2035, 6.0)]]
    ... )
    >>> growth = growth_by_period(
    ...     table, [ON, QC], 2022, [2025, 2030], 5, DemandProjectionPoint.PeriodEnd
    ... )
    >>> list(zip([r.short() for r in growth["region"]], growth["period"], growth["growth"], growth["source"]))
    [('ON', 2025, 1.2, 'national'), ('ON', 2030, 1.5, 'national'), ('QC', 2025, 1.25, 'Quebec'), ('QC', 2030, 1.5, 'Quebec')]
    """
    national = table.loc[table["region"].isna()]
    rows: list[tuple[CANOEProvince, int, float, str]] = []
    for province in provinces:
        own = table.loc[table["region"].isin([province])]
        series_rows = own if not own.empty else national
        if series_rows.empty:
            raise ValueError(f"No series for {province.short()} nor national rows")
        series = pd.Series(
            series_rows["value"].to_numpy(), index=series_rows["year"].to_numpy()
        )
        level = "own" if not own.empty else "national"
        if index_year not in series.index:
            raise ValueError(
                f"{province.short()} ({level} series): no value in {index_year}, the "
                + "year of the base data it scales"
            )
        try:
            growth = projected_growth_by_period(
                series / float(series.loc[index_year]),
                future_periods,
                period_step,
                projection_point,
            )
        except KeyError as error:
            raise ValueError(
                f"{province.short()} ({level} series): no value in {error.args[0]}, "
                + f"a year read ({projection_point.value})"
            ) from error
        source = str(series_rows["source"].iloc[0])
        rows.extend(
            (province, period, factor, source) for period, factor in growth.items()
        )
    return pd.DataFrame(rows, columns=["region", "period", "growth", "source"])


def projected_growth_by_period(
    index: pd.Series,
    future_periods: list[int],
    period_step: int,
    projection_point: DemandProjectionPoint,
) -> dict[int, float]:
    """
    Growth factor of each model period of a projected series, to multiply base-year
    demands by.

    Parameters
    ----------
    index : pd.Series
        The series by year (index), relative to the year of the base demand data.
    future_periods : list[int]
        The model periods.
    period_step : int
        Length of the last period, see `canoe.common.periods.period_end_years`.
    projection_point : DemandProjectionPoint
        Year of each period at which the series is read.

    Returns
    -------
    dict[int, float]
        Model period -> growth factor.

    Raises
    ------
    KeyError
        If a year read is not in the series.

    Examples
    --------
    >>> index = pd.Series([1.0, 1.1, 1.2, 1.5], index=[2022, 2025, 2030, 2035])
    >>> projected_growth_by_period(index, [2025, 2030], 5, DemandProjectionPoint.PeriodEnd)
    {2025: 1.2, 2030: 1.5}
    >>> projected_growth_by_period(index, [2025, 2030], 5, DemandProjectionPoint.PeriodStart)
    {2025: 1.1, 2030: 1.2}
    >>> growth = projected_growth_by_period(index, [2025, 2030], 5, DemandProjectionPoint.Legacy)
    >>> {period: round(factor, 4) for period, factor in growth.items()}
    {2025: 1.0, 2030: 1.0909}
    """
    if projection_point == DemandProjectionPoint.PeriodEnd:
        return {
            period: float(index.loc[end_year])
            for period, end_year in period_end_years(
                future_periods, period_step
            ).items()
        }
    if projection_point == DemandProjectionPoint.PeriodStart:
        return {period: float(index.loc[period]) for period in future_periods}
    first_period_value = float(index.loc[future_periods[0]])
    return {
        period: float(index.loc[period]) / first_period_value
        for period in future_periods
    }


def growth_notes(growth: pd.DataFrame) -> str:
    """
    The sources of the series in `growth` (see `growth_by_period`), for notes.

    Examples
    --------
    >>> growth_notes(pd.DataFrame({"source": ["CER", "CER", "StatCan"]}))
    'CER; StatCan'
    """
    return "; ".join(dict.fromkeys(str(s) for s in growth["source"]))

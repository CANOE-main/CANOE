"""
Central emissions step of the pipeline.

- `init`, before the modules run: registers the gas commodities (`CANOEEmission`) and
  the CO2-equivalent commodity, and the cost of CO2-equivalent emissions if configured,
  under the electricity sector's data set. Modules can then write emission activities
  that reference those commodities.
- `finalize`, after the modules run: checks the modules' emission declarations against
  the emission activities in the database, then adds a CO2-equivalent row for every
  emitting flow (with the `data_id` of its gas rows), weighting the gases by the
  configured global warming potentials.

Modules only write the real gases; CO2-equivalents are always derived here, so every
sector uses the same weights.
"""

from itertools import product
from sqlite3 import Connection

import pandas as pd
from canoe_schema.v4_0 import (
    Commodity,
    CommodityTypeCode,
    CostEmission,
    DataSet,
    EmissionActivity,
    Technology,
)
from loguru import logger

from canoe.common import (
    CANOEEmission,
    CANOEEmissionDeclaration,
    CANOEProvince,
)
from canoe.common.db_tools import write_label
from canoe.common.naming import (
    DatasetIdentifier,
    get_co2_equivalent_commodity_name,
    get_emission_commodity_name,
)
from canoe.emissions.config import EmissionsConfig


def init(
    db_conn: Connection,
    config: EmissionsConfig,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    data_id: DatasetIdentifier,
) -> None:
    """
    Register the emission commodities (and their cost), before the modules run.

    params:
    - model_periods: periods the cost of CO2-equivalents is written for
    - data_id: data set of these rows (the electricity sector's), registered here for
      the whole sector and each province
    """
    datasets = [
        DataSet(data_id=data_id.get_dataset_code(province=province))
        for province in [*provinces, None]
    ]
    sql, params = DataSet.bulk_insert_or_ignore_sql(
        datasets, include_nulls=True, include_defaults=True
    )
    db_conn.executemany(sql, params)

    commodities = [
        Commodity(
            name=get_emission_commodity_name(emission),
            flag=CommodityTypeCode.E,
            description=f"{emission.get_desc_name()} ({emission.value}) emissions",
            units="kt",
            data_id=data_id.get_dataset_code(),
        )
        for emission in CANOEEmission
    ] + [
        Commodity(
            name=get_co2_equivalent_commodity_name(),
            flag=CommodityTypeCode.E,
            description=(
                f"CO2-equivalent emissions ({config.gwp.get_desc_name()} global "
                "warming potentials)"
            ),
            units="ktCO2e",
            data_id=data_id.get_dataset_code(),
        )
    ]
    for commodity in commodities:
        write_label(db_conn, commodity)
        sql, params = Commodity.to_insert_or_ignore_sql(commodity)
        db_conn.execute(sql, params)

    if config.cost_of_co2e is not None:
        cost_emissions = [
            CostEmission(
                region=province.short(),
                period=period,
                emis_comm=get_co2_equivalent_commodity_name(),
                cost=config.cost_of_co2e,
                units=config.cost_units,
                data_id=data_id.get_dataset_code(province=province),
            )
            for province, period in product(provinces, model_periods)
        ]
        sql, params = CostEmission.bulk_insert_or_ignore_sql(
            cost_emissions, include_nulls=True
        )
        db_conn.executemany(sql, params)


def finalize(
    db_conn: Connection,
    config: EmissionsConfig,
    declarations: list[CANOEEmissionDeclaration],
) -> None:
    """
    Check the modules' emission declarations and write the CO2-equivalent rows, after
    the modules run.

    Raises
    ------
    ValueError
        If a module wrote CO2-equivalent rows itself, or emission activities for a gas
        its sector did not declare.
    """
    activities = _read_gas_activities(db_conn)
    _check_declarations(activities, declarations)
    _write_co2_equivalents(db_conn, activities, config)


def _read_gas_activities(db_conn: Connection) -> pd.DataFrame:
    """Emission activities of the gases, with the sector of their technology"""
    activities = pd.read_sql_query(
        f"""
        SELECT a.region, a.emis_comm, a.input_comm, a.tech, a.vintage, a.output_comm,
               a.activity, a.units, a.data_id, t.sector
        FROM {EmissionActivity.__table_name__} a
        LEFT JOIN {Technology.__table_name__} t ON t.tech = a.tech
        """,
        db_conn,
    )
    co2e_rows = activities[
        activities["emis_comm"] == get_co2_equivalent_commodity_name()
    ]
    if not co2e_rows.empty:
        raise ValueError(
            "CO2-equivalent emission activities are derived by the central emissions "
            + f"step; modules must only write the gases. Found for: {sorted(set(co2e_rows['tech']))}"
        )
    return activities


def _check_declarations(
    activities: pd.DataFrame, declarations: list[CANOEEmissionDeclaration]
) -> None:
    declared = {
        (d.sector.name.lower(), get_emission_commodity_name(d.emission))
        for d in declarations
    }
    written = set(zip(activities["sector"], activities["emis_comm"]))

    undeclared = written - declared
    if undeclared:
        raise ValueError(
            "Emission activities written for (sector, emission) pairs no module "
            + f"declared: {sorted(undeclared, key=str)}"
        )
    for sector, emission in sorted(declared - written):
        logger.warning(
            f"Sector `{sector}` declared `{emission}` emissions but wrote no emission "
            + "activities for it"
        )


def _write_co2_equivalents(
    db_conn: Connection, activities: pd.DataFrame, config: EmissionsConfig
) -> None:
    """One CO2-equivalent row per emitting flow: sum of the gases weighted by the GWPs"""
    if activities.empty:
        return
    gwp = {
        get_emission_commodity_name(emission): factor
        for emission, factor in config.gwp.factors().items()
    }
    flow = ["region", "input_comm", "tech", "vintage", "output_comm", "data_id"]

    mixed_units = activities.groupby(flow)["units"].nunique(dropna=False) > 1
    if mixed_units.any():
        raise ValueError(
            "The gases of an emitting flow must share units to add them up. Mixed "
            + f"units for: {list(mixed_units[mixed_units].index)[:5]}"
        )

    weighted = activities.assign(
        co2e=activities["activity"] * activities["emis_comm"].map(gwp)
    )
    co2e = weighted.groupby(flow, as_index=False).agg(
        activity=("co2e", "sum"), units=("units", "first")
    )

    notes = (
        f"Sum of the {', '.join(e.value for e in CANOEEmission)} emission activities "
        + f"weighted by their {config.gwp.get_desc_name()} global warming potentials"
    )
    co2e_activities = [
        EmissionActivity(
            region=row.region,
            emis_comm=get_co2_equivalent_commodity_name(),
            input_comm=row.input_comm,
            tech=row.tech,
            vintage=row.vintage,
            output_comm=row.output_comm,
            activity=row.activity,
            units=row.units,
            notes=notes if i == 0 else None,
            data_id=row.data_id,
        )
        for i, row in enumerate(co2e.itertuples(index=False))
    ]
    sql, params = EmissionActivity.bulk_insert_or_ignore_sql(
        co2e_activities, include_nulls=True
    )
    db_conn.executemany(sql, params)

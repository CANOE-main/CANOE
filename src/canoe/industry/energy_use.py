"""
Industry energy use by province and subsector from the NRCan CEUD industry tables.

The CEUD publishes one table per province and subsector, except for the Atlantic
provinces, which share the Atlantic tables. Their energy use is split with the
StatCan shares of each province in each subsector (see
`loaders.get_statcan_atlantic_industry_shares`), assuming the four provinces have
the fuel mix of the Atlantic region. Nothing in here touches the database.
"""

import pandas as pd
from loguru import logger

from canoe.common import CANOEProvince, GoldConnectorConfig
from canoe.common.ceud import CEUDEnergyUse
from canoe.common.validation import ValidationBehavior, handle_validation_issue

from .loaders import get_ceud_industry_energy_use
from .subsectors import IndustrySubsector

type CEUDIndustryTables = dict[CANOEProvince, dict[IndustrySubsector, CEUDEnergyUse]]
"""CEUD table of each province (the Atlantic provinces share the Atlantic tables)
and subsector."""

type AtlanticShares = dict[IndustrySubsector, dict[CANOEProvince, float]]
"""Share of each Atlantic province in the Atlantic table of each subsector."""


def load_ceud_tables(
    provinces: list[CANOEProvince],
    subsectors: list[IndustrySubsector],
    data_year: int,
    cache_config: GoldConnectorConfig,
) -> CEUDIndustryTables:
    """
    CEUD industry energy use of each province's tables (the Atlantic provinces get
    the Atlantic tables) for `subsectors`, reading each table once.
    """
    tables: dict[str, dict[IndustrySubsector, CEUDEnergyUse]] = {}
    for code in dict.fromkeys(province.get_nrcan_code() for province in provinces):
        tables[code] = {
            subsector: get_ceud_industry_energy_use(
                code, subsector, data_year, cache_config
            )
            for subsector in subsectors
        }
    return {province: tables[province.get_nrcan_code()] for province in provinces}


def compute_energy_use(
    ceud: CEUDIndustryTables, atlantic_shares: AtlanticShares
) -> pd.DataFrame:
    """
    Energy use of each province and subsector, all sources.

    params:
    - ceud: CEUD tables of each province, see `load_ceud_tables`
    - atlantic_shares: see `loaders.get_statcan_atlantic_industry_shares`

    Returns province, subsector, energy_use (PJ; NaN where NRCan does not publish it)

    Examples
    --------
    >>> table = CEUDEnergyUse(total=8.0, by_source=pd.DataFrame())
    >>> NS, ON = CANOEProvince.NOVA_SCOTIA, CANOEProvince.ONTARIO
    >>> cement = IndustrySubsector.Cement
    >>> compute_energy_use(
    ...     {ON: {cement: table}, NS: {cement: table}}, {cement: {NS: 0.25}}
    ... )
          province subsector  energy_use
    0      Ontario    Cement         8.0
    1  Nova Scotia    Cement         2.0
    """
    return pd.DataFrame(
        [
            {
                "province": province,
                "subsector": subsector,
                "energy_use": table.total
                * _atlantic_factor(province, subsector, atlantic_shares),
            }
            for province, tables in ceud.items()
            for subsector, table in tables.items()
        ],
        columns=["province", "subsector", "energy_use"],
    )


def compute_energy_use_by_source(
    ceud: CEUDIndustryTables, atlantic_shares: AtlanticShares
) -> pd.DataFrame:
    """
    Energy use of each province and subsector by energy source.

    params:
    - ceud: CEUD tables of each province, see `load_ceud_tables`
    - atlantic_shares: see `loaders.get_statcan_atlantic_industry_shares`

    Returns province, subsector, source (NRCan label), fuel (`CANOEFuel`), energy_use
    (PJ) and share (fraction of the subsector's total energy use in the province,
    from the percentages NRCan publishes; the Atlantic provinces share the Atlantic
    fuel mix). Values NRCan does not publish are NaN.

    Examples
    --------
    >>> import numpy as np
    >>> from canoe.common import CANOEFuel
    >>> by_source = pd.DataFrame(
    ...     {
    ...         "fuel": [CANOEFuel.Electricity, CANOEFuel.Coal],
    ...         "energy_use": [6.0, np.nan],
    ...         "share": [75.0, np.nan],
    ...     },
    ...     index=pd.Index(["Electricity", "Coal"], name="source"),
    ... )
    >>> table = CEUDEnergyUse(total=8.0, by_source=by_source)
    >>> NS, cement = CANOEProvince.NOVA_SCOTIA, IndustrySubsector.Cement
    >>> compute_energy_use_by_source({NS: {cement: table}}, {cement: {NS: 0.5}})
          province subsector       source         fuel  energy_use  share
    0  Nova Scotia    Cement  Electricity  Electricity         3.0   0.75
    1  Nova Scotia    Cement         Coal         Coal         NaN    NaN
    """
    frames: list[pd.DataFrame] = []
    for province, tables in ceud.items():
        for subsector, table in tables.items():
            df = table.by_source.reset_index()
            df["province"] = province
            df["subsector"] = subsector
            df["energy_use"] = df["energy_use"] * _atlantic_factor(
                province, subsector, atlantic_shares
            )
            df["share"] = df["share"] / 100
            frames.append(df)
    return pd.concat(frames, ignore_index=True)[
        ["province", "subsector", "source", "fuel", "energy_use", "share"]
    ]  # pyright: ignore[reportReturnType]


def check_energy_use(
    energy_use: pd.DataFrame, missing_data_behavior: ValidationBehavior
):
    """
    Check every modelled subsector has energy use data in every province.

    Energy use NRCan does not publish is handled by `missing_data_behavior`;
    subsectors with no energy use in a province are only logged, as they are left
    out there.

    params:
    - energy_use: see `compute_energy_use`
    """
    missing = energy_use[energy_use["energy_use"].isna()]
    for province, subsector in zip(missing["province"], missing["subsector"]):
        handle_validation_issue(
            f"CEUD industry energy use missing for {subsector.get_desc_name()} in "
            + f"{province}",
            missing_data_behavior,
        )
    unused = energy_use[energy_use["energy_use"] == 0]
    for province, df in unused.groupby("province", sort=False):
        logger.info(
            f"No industry energy use in {province} for "
            + ", ".join(s.get_desc_name() for s in df["subsector"])
            + "; left out there"
        )


def check_atlantic_shares(
    ceud: CEUDIndustryTables,
    atlantic_shares: AtlanticShares,
    missing_data_behavior: ValidationBehavior,
):
    """
    Check the energy use of every Atlantic table reaches the Atlantic provinces: a
    subsector with energy use in the Atlantic table and no StatCan share in any
    Atlantic province would lose it. Handled by `missing_data_behavior`.

    params:
    - ceud: CEUD tables of each province, see `load_ceud_tables`
    - atlantic_shares: see `loaders.get_statcan_atlantic_industry_shares`

    Examples
    --------
    >>> NS, steel = CANOEProvince.NOVA_SCOTIA, IndustrySubsector.IronAndSteel
    >>> table = CEUDEnergyUse(total=8.0, by_source=pd.DataFrame())
    >>> check_atlantic_shares({NS: {steel: table}}, {steel: {NS: 0.0}}, "error")
    Traceback (most recent call last):
    ...
    ValueError: ...8.0 PJ of iron and steel in the CEUD Atlantic tables...
    """
    atlantic = next((t for p, t in ceud.items() if p.is_atlantic()), None)
    if atlantic is None:
        return
    for subsector, table in atlantic.items():
        if table.total > 0 and sum(atlantic_shares[subsector].values()) == 0:
            handle_validation_issue(
                f"{table.total} PJ of {subsector.get_desc_name()} in the CEUD "
                + "Atlantic tables, but no Atlantic province has a StatCan share of "
                + "it; left out",
                missing_data_behavior,
            )


def _atlantic_factor(
    province: CANOEProvince,
    subsector: IndustrySubsector,
    atlantic_shares: AtlanticShares,
) -> float:
    """Share of `province` in its CEUD table: 1, or its StatCan share if Atlantic"""
    if not province.is_atlantic():
        return 1.0
    shares = atlantic_shares.get(subsector, {})
    if province not in shares:
        raise ValueError(
            f"No share to split the Atlantic CEUD {subsector.get_desc_name()} table "
            + f"for {province}"
        )
    return shares[province]

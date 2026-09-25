"""
Agriculture energy use by province from the NRCan CEUD agriculture tables.

The CEUD publishes one table per province, except for the Atlantic provinces, which
share a single table. Their energy use is split with the StatCan shares of each
province (see `loaders.get_statcan_atlantic_agriculture_shares`), assuming the four
provinces have the fuel mix of the Atlantic region. Nothing in here touches the
database.
"""

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel, CANOEProvince, GoldConnectorConfig
from canoe.common.validation import ValidationBehavior, handle_validation_issue

from .loaders import CEUDAgricultureEnergyUse, get_ceud_agriculture_energy_use


def load_ceud_tables(
    provinces: list[CANOEProvince],
    data_year: int,
    cache_config: GoldConnectorConfig,
) -> dict[CANOEProvince, CEUDAgricultureEnergyUse]:
    """
    CEUD agriculture energy use of each province's table (the Atlantic provinces get
    the Atlantic table), reading each table once.
    """
    tables: dict[str, CEUDAgricultureEnergyUse] = {}
    for code in dict.fromkeys(province.get_nrcan_code() for province in provinces):
        tables[code] = get_ceud_agriculture_energy_use(code, data_year, cache_config)
    return {province: tables[province.get_nrcan_code()] for province in provinces}


def compute_total_energy_use(
    ceud: dict[CANOEProvince, CEUDAgricultureEnergyUse],
    atlantic_shares: dict[CANOEProvince, float],
) -> pd.DataFrame:
    """
    Total agriculture energy use of each province, all sources.

    params:
    - ceud: CEUD table of each province, see `load_ceud_tables`
    - atlantic_shares: share of each Atlantic province in the Atlantic table

    Returns province, energy_use (PJ)

    Examples
    --------
    >>> table = CEUDAgricultureEnergyUse(total=8.0, by_source=pd.DataFrame())
    >>> compute_total_energy_use(
    ...     {CANOEProvince.ONTARIO: table, CANOEProvince.NOVA_SCOTIA: table},
    ...     {CANOEProvince.NOVA_SCOTIA: 0.25},
    ... )
          province  energy_use
    0      Ontario         8.0
    1  Nova Scotia         2.0
    """
    return pd.DataFrame(
        {
            "province": list(ceud),
            "energy_use": [
                table.total * _atlantic_factor(province, atlantic_shares)
                for province, table in ceud.items()
            ],
        }
    )


def compute_energy_use_by_source(
    ceud: dict[CANOEProvince, CEUDAgricultureEnergyUse],
    atlantic_shares: dict[CANOEProvince, float],
) -> pd.DataFrame:
    """
    Agriculture energy use of each province by energy source.

    params:
    - ceud: CEUD table of each province, see `load_ceud_tables`
    - atlantic_shares: share of each Atlantic province in the Atlantic table

    Returns province, source (NRCan label), fuel (`CANOEFuel`, missing (NaN) for
    sources with no CANOE fuel), energy_use (PJ) and share (fraction of the province's total
    energy use, from the percentages NRCan publishes; the Atlantic provinces share the
    Atlantic fuel mix). Values NRCan does not publish are NaN.

    Examples
    --------
    >>> by_source = pd.DataFrame(
    ...     {
    ...         "fuel": [CANOEFuel.Electricity, None],
    ...         "energy_use": [6.0, 2.0],
    ...         "share": [75.0, 25.0],
    ...     },
    ...     index=pd.Index(["Electricity", "Steam"], name="source"),
    ... )
    >>> table = CEUDAgricultureEnergyUse(total=8.0, by_source=by_source)
    >>> compute_energy_use_by_source(
    ...     {CANOEProvince.NOVA_SCOTIA: table}, {CANOEProvince.NOVA_SCOTIA: 0.5}
    ... )
          province       source         fuel  energy_use  share
    0  Nova Scotia  Electricity  Electricity         3.0   0.75
    1  Nova Scotia        Steam          NaN         1.0   0.25
    """
    frames: list[pd.DataFrame] = []
    for province, table in ceud.items():
        df = table.by_source.reset_index()
        df["province"] = province
        df["energy_use"] = df["energy_use"] * _atlantic_factor(
            province, atlantic_shares
        )
        df["share"] = df["share"] / 100
        frames.append(df)
    return pd.concat(frames, ignore_index=True)[
        ["province", "source", "fuel", "energy_use", "share"]
    ]  # pyright: ignore[reportReturnType]


def check_fuel_data(
    energy_use_by_source: pd.DataFrame,
    fuels: list[CANOEFuel],
    missing_data_behavior: ValidationBehavior,
):
    """
    Check the CEUD has data for every requested fuel in every province.

    Missing values (not published by NRCan) are handled by `missing_data_behavior`;
    fuels with no energy use are only logged, as they are left out of the province.

    params:
    - energy_use_by_source: see `compute_energy_use_by_source`
    - fuels: fuels requested in the config
    """
    for province, df in energy_use_by_source.groupby("province", sort=False):
        for fuel in fuels:
            # Each fuel has a single CEUD source
            row = df[df["fuel"].isin([fuel])].iloc[0]
            energy_use = float(row["energy_use"])
            share = float(row["share"])
            if np.isnan(energy_use) or np.isnan(share):
                handle_validation_issue(
                    f"CEUD agriculture data missing for {fuel.get_desc_name()} in "
                    + f"{province} (energy use: {energy_use} PJ, share: {share})",
                    missing_data_behavior,
                )
            elif energy_use == 0:
                logger.info(
                    f"No agriculture {fuel.get_desc_name()} use in {province}, left out"
                )


def _atlantic_factor(
    province: CANOEProvince, atlantic_shares: dict[CANOEProvince, float]
) -> float:
    """Share of `province` in its CEUD table: 1, or its StatCan share if Atlantic"""
    if not province.is_atlantic():
        return 1.0
    if province not in atlantic_shares:
        raise ValueError(f"No share to split the Atlantic CEUD table for {province}")
    return atlantic_shares[province]

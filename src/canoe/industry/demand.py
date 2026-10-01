"""
Energy demand of the industry subsectors: the CEUD energy use of each subsector in
each province, projected with GDP. Nothing in here touches the database.
"""

from enum import StrEnum

import numpy as np
import pandas as pd
from loguru import logger

from canoe.common import CANOEFuel
from canoe.common.validation import ValidationBehavior, handle_validation_issue

_KEYS = ["province", "subsector"]


class OtherFuelsTreatment(StrEnum):
    """
    What happens to the NRCan CEUD "Other" energy source (`OTH`) of the industry
    subsectors. It is a mix of non-standard fuels (e.g. waste fuels in cement) with no
    price or emission factors in the fuel module, so it is never a fuel import. See
    `INDUSTRY_MODULE_BUGS.md`, 1.
    """

    Deduct = "deduct"
    """Leave "Other" out: its energy use is deducted from the demand of the
    subsector, and the input splits are the shares of the rest of its energy use. The
    modelled fuels meet only the energy use they met in the CEUD year."""

    Free = "free"
    """Keep "Other" as an input of the subsectors that use it (`I_oth`), with its
    CEUD share as input split, supplied by the industry module at no cost and with no
    emissions. The demand is all the energy use of the subsector. Reproduces the
    previous module (free `F_I_OTH`)."""


def compute_demand(
    energy_use: pd.DataFrame,
    energy_use_by_source: pd.DataFrame,
    shares: pd.DataFrame,
    gdp_growth: dict[int, float],
    other_fuels: OtherFuelsTreatment,
) -> pd.DataFrame:
    """
    Energy demand of each province and subsector over the model periods: the energy
    use of the CEUD year times the GDP growth of each period. With `deduct`, the
    energy use of "Other" fuels is taken out first: the published PJ, or its share
    (see `input_splits.compute_ceud_shares`) of the total where NRCan does not
    publish it.

    params:
    - energy_use: see `energy_use.compute_energy_use`
    - energy_use_by_source: see `energy_use.compute_energy_use_by_source`
    - shares: see `input_splits.compute_ceud_shares`
    - gdp_growth: model period -> gdp growth factor from the CEUD year, see
      `canoe.common.gdp.gdp_growth_by_period`
    - other_fuels: what happens to "Other" fuels

    Returns region, period, subsector, demand (PJ; NaN where the energy use is not
    published)

    Examples
    --------
    >>> from canoe.common import CANOEProvince
    >>> from canoe.industry.subsectors import IndustrySubsector
    >>> keys = {"province": CANOEProvince.ONTARIO, "subsector": IndustrySubsector.Cement}
    >>> energy_use = pd.DataFrame([{**keys, "energy_use": 10.0}])
    >>> by_source = pd.DataFrame(
    ...     [{**keys, "fuel": CANOEFuel.Other, "energy_use": 1.0, "share": 0.1}]
    ... )
    >>> shares = by_source[["province", "subsector", "fuel", "share"]]
    >>> growth = {2025: 1.0, 2030: 1.2}
    >>> compute_demand(energy_use, by_source, shares, growth, OtherFuelsTreatment.Deduct)
        region  period subsector  demand
    0  Ontario    2025    Cement     9.0
    1  Ontario    2030    Cement    10.8
    >>> compute_demand(energy_use, by_source, shares, growth, OtherFuelsTreatment.Free)
        region  period subsector  demand
    0  Ontario    2025    Cement    10.0
    1  Ontario    2030    Cement    12.0
    """
    base = energy_use[[*_KEYS, "energy_use"]].copy()
    if other_fuels == OtherFuelsTreatment.Deduct:
        other = (
            energy_use_by_source.loc[
                energy_use_by_source["fuel"].isin([CANOEFuel.Other])
            ]
            .merge(shares, on=[*_KEYS, "fuel"], suffixes=("", "_used"))
            .merge(
                energy_use[[*_KEYS, "energy_use"]], on=_KEYS, suffixes=("", "_total")
            )
        )
        other_energy = np.where(
            other["energy_use"].isna(),
            other["share_used"] * other["energy_use_total"],
            other["energy_use"],
        )
        deducted = other[_KEYS].assign(other=other_energy)
        base = base.merge(deducted, on=_KEYS, how="left")
        base["energy_use"] = base["energy_use"] - base["other"].fillna(0.0)

    periods = pd.DataFrame(
        {"period": list(gdp_growth), "growth": list(gdp_growth.values())}
    )
    demand = base.merge(periods, how="cross")
    demand["demand"] = demand["energy_use"] * demand["growth"]
    return demand.rename(columns={"province": "region"})[
        ["region", "period", "subsector", "demand"]
    ]  # pyright: ignore[reportReturnType]


def align_demand_and_splits(
    demand: pd.DataFrame,
    input_splits: pd.DataFrame,
    missing_data_behavior: ValidationBehavior,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    The demand and input splits of the (region, subsector) with both a positive
    demand and a positive split: a technology without demand would be unused, a
    demand without fuels could not be met.

    A positive demand with no positive split (none of the subsector's fuels has a
    share in the province, e.g. a `fuels` override without its main fuel) is
    reported with `missing_data_behavior` and left out.

    params:
    - demand: see `compute_demand`
    - input_splits: see `input_splits.compute_input_splits`

    Returns the demand and input splits kept, with the columns given
    """
    keys = ["region", "subsector"]
    with_demand = demand.loc[demand["demand"] > 0, keys].drop_duplicates()
    with_fuels = input_splits.loc[input_splits["split"] > 0, keys].drop_duplicates()
    kept = with_demand.merge(with_fuels, on=keys)

    unmet = with_demand.merge(with_fuels, on=keys, how="left", indicator=True)
    for region, subsector in zip(
        *(unmet.loc[unmet["_merge"] == "left_only", k] for k in keys)
    ):
        handle_validation_issue(
            f"No fuel of {subsector.get_desc_name()} has a share of its energy use in "
            + f"{region}; left out there",
            missing_data_behavior,
        )
    logger.debug(f"Industry subsectors modelled in {len(kept)} (region, subsector)")
    return (
        demand.merge(kept, on=keys)[demand.columns],
        input_splits.merge(kept, on=keys)[input_splits.columns],
    )  # pyright: ignore[reportReturnType]

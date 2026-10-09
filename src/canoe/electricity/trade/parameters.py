"""
Parameters of the trade of electricity: interties between modelled provinces, whose
flows the model decides, and boundary interties (with the US, or with a province not
modelled), fixed to their historical flows.

CODERS hourly data are in each province's local time, and are used as they are on
the model's EST time slices (see `ELECTRICITY_MODULE_BUGS.md`).
"""

from typing import cast

import numpy as np
import pandas as pd

from canoe.common import CANOEProvince


def intertie_losses(
    system_losses: pd.DataFrame,
    transmission_losses: pd.DataFrame,
    provinces: list[CANOEProvince],
    reproduce_previous_intertie_losses: bool,
) -> dict[CANOEProvince, float]:
    """
    Losses (fraction) of the electricity a province sends out on its interties: its
    transmission losses. The electricity then enters the receiving grid at the
    transmission level, where it pays that grid's losses on its way to the
    consumers. The previous module took the system losses (transmission and
    distribution) instead (`reproduce_previous_intertie_losses`).

    Parameters
    ----------
    system_losses : pd.DataFrame
        Columns `region` and `line_losses`, see `loaders.get_coders_system_line_losses`.
    transmission_losses : pd.DataFrame
        Columns `region` and `losses`, see `loaders.get_coders_transmission_losses`.
    provinces : list[CANOEProvince]
        Provinces modelled; every one needs its losses.

    Raises
    ------
    ValueError
        If a province has no losses.

    Examples
    --------
    >>> ON = CANOEProvince.ONTARIO
    >>> system = pd.DataFrame({"region": [ON], "line_losses": [0.08]})
    >>> transmission = pd.DataFrame({"region": [ON], "losses": [0.025]})
    >>> intertie_losses(system, transmission, [ON], False)[ON]
    0.025
    >>> intertie_losses(system, transmission, [ON], True)[ON]
    0.08
    """
    losses = (
        dict(zip(system_losses["region"], system_losses["line_losses"]))
        if reproduce_previous_intertie_losses
        else dict(zip(transmission_losses["region"], transmission_losses["losses"]))
    )
    missing = [p.short() for p in provinces if p not in losses]
    if missing:
        raise ValueError(f"No intertie losses for {missing}")
    return {p: float(losses[p]) for p in provinces}


def endogenous_interties(
    interfaces: pd.DataFrame, provinces: list[CANOEProvince]
) -> pd.DataFrame:
    """
    The transfer capability between modelled provinces in each direction, the
    interties of each direction summed.

    Parameters
    ----------
    interfaces : pd.DataFrame
        See `loaders.get_coders_interface_capacities`.
    provinces : list[CANOEProvince]
        Provinces modelled.

    Returns
    -------
    pd.DataFrame
        Columns `from_region`, `to_region` (`CANOEProvince`), `ttc_summer`,
        `ttc_winter` (MW) and `interties` (names), one row per direction.

    Raises
    ------
    ValueError
        If a direction has no reverse (Temoa needs both).

    Examples
    --------
    >>> interfaces = pd.DataFrame(
    ...     {"from_region": ["AB", "AB", "BC", "AB"], "to_region": ["BC", "BC", "AB", "USA"],
    ...      "ttc_summer": [157.0, 800.0, 1157.0, 315.0],
    ...      "ttc_winter": [188.0, 800.0, 1188.0, 315.0],
    ...      "interties": ["A", "B", "A; B", "C"]}
    ... )
    >>> AB, BC = CANOEProvince.ALBERTA, CANOEProvince.BRITISH_COLUMBIA
    >>> endogenous_interties(interfaces, [AB, BC])[["ttc_summer", "ttc_winter", "interties"]]
       ttc_summer  ttc_winter interties
    0       957.0       988.0      A; B
    1      1157.0      1188.0      A; B
    """
    modelled = {p.short(): p for p in provinces}
    inside = interfaces.loc[
        interfaces["from_region"].isin(modelled)
        & interfaces["to_region"].isin(modelled)
    ]
    grouped = (
        inside.groupby(["from_region", "to_region"], sort=False)
        .agg(
            ttc_summer=("ttc_summer", "sum"),
            ttc_winter=("ttc_winter", "sum"),
            interties=("interties", "; ".join),
        )
        .reset_index()
    )
    directions = set(zip(grouped["from_region"], grouped["to_region"]))
    missing = sorted(f"{t}-{f}" for f, t in directions if (t, f) not in directions)
    if missing:
        raise ValueError(f"CODERS interface capacities: no reverse direction {missing}")
    return pd.DataFrame(
        {
            "from_region": grouped["from_region"].map(modelled),
            "to_region": grouped["to_region"].map(modelled),
            "ttc_summer": grouped["ttc_summer"].astype(float),
            "ttc_winter": grouped["ttc_winter"].astype(float),
            "interties": grouped["interties"],
        }
    )


def intertie_capacities(interties: pd.DataFrame) -> pd.DataFrame:
    """
    Capacity (GW) of each direction: the largest transfer capability of the pair, in
    either season and direction, as Temoa needs the same capacity both ways.

    Parameters
    ----------
    interties : pd.DataFrame
        See `endogenous_interties`.

    Returns
    -------
    pd.DataFrame
        Columns `from_region`, `to_region` and `capacity`.

    Examples
    --------
    >>> AB, BC = CANOEProvince.ALBERTA, CANOEProvince.BRITISH_COLUMBIA
    >>> interties = pd.DataFrame(
    ...     {"from_region": [AB, BC], "to_region": [BC, AB],
    ...      "ttc_summer": [957.0, 1157.0], "ttc_winter": [988.0, 1188.0]}
    ... )
    >>> intertie_capacities(interties)["capacity"].tolist()
    [1.188, 1.188]
    """
    MW_TO_GW = 1e-3
    largest = interties[["ttc_summer", "ttc_winter"]].max(axis=1)
    by_direction = dict(
        zip(zip(interties["from_region"], interties["to_region"]), largest)
    )
    return pd.DataFrame(
        {
            "from_region": interties["from_region"],
            "to_region": interties["to_region"],
            "capacity": [
                max(by_direction[(f, t)], by_direction[(t, f)]) * MW_TO_GW
                for f, t in zip(interties["from_region"], interties["to_region"])
            ],
        }
    )


def intertie_capacity_factors(
    interties: pd.DataFrame, capacities: pd.DataFrame, tolerance: float
) -> pd.DataFrame:
    """
    Hourly capacity factor of each direction: its transfer capability in the season
    of the hour (summer from May to October) over the pair's capacity; below
    `tolerance`, 0. Only for the pairs whose capability changes with the season or
    direction (the others are always at full capacity).

    Parameters
    ----------
    interties : pd.DataFrame
        See `endogenous_interties`.
    capacities : pd.DataFrame
        See `intertie_capacities`.
    tolerance : float
        Smallest capacity factor kept.

    Returns
    -------
    pd.DataFrame
        Columns `from_region`, `to_region`, `hour` (0-8759) and `factor`.

    Examples
    --------
    >>> AB, BC = CANOEProvince.ALBERTA, CANOEProvince.BRITISH_COLUMBIA
    >>> interties = pd.DataFrame(
    ...     {"from_region": [AB, BC], "to_region": [BC, AB],
    ...      "ttc_summer": [600.0, 1000.0], "ttc_winter": [800.0, 1000.0]}
    ... )
    >>> capacities = intertie_capacities(interties)
    >>> factors = intertie_capacity_factors(interties, capacities, 0.01)
    >>> factors.groupby(["from_region", "factor"]).size()
    from_region       factor
    Alberta           0.6       4416
                      0.8       4344
    British Columbia  1.0       8760
    dtype: int64
    """
    GW_TO_MW = 1e3
    DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    SUMMER_MONTHS = range(5, 11)  # May to October
    month_of_hour = np.repeat(np.arange(1, 13), np.array(DAYS_IN_MONTH) * 24)
    is_summer = np.isin(month_of_hour, SUMMER_MONTHS)
    capability = {
        (f, t): (summer, winter)
        for f, t, summer, winter in zip(
            interties["from_region"],
            interties["to_region"],
            interties["ttc_summer"],
            interties["ttc_winter"],
        )
    }
    capacity = dict(
        zip(
            zip(capacities["from_region"], capacities["to_region"]),
            capacities["capacity"],
        )
    )
    frames: list[pd.DataFrame] = []
    for (f, t), (summer, winter) in capability.items():
        if len({summer, winter, *capability[(t, f)]}) == 1:
            continue
        factor = np.where(is_summer, summer, winter) / (capacity[(f, t)] * GW_TO_MW)
        factor[factor < tolerance] = 0.0
        frames.append(
            pd.DataFrame(
                {
                    "from_region": f,
                    "to_region": t,
                    "hour": range(8760),
                    "factor": factor,
                }
            )
        )
    columns = ["from_region", "to_region", "hour", "factor"]
    return (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=columns)
    )


def boundary_flows(
    transfers: pd.DataFrame, provinces: list[CANOEProvince]
) -> pd.DataFrame:
    """
    Hourly flows out of and into each modelled province on its boundary interties
    (those whose other end is not modelled: the US, or a province left out), summed
    by outside region.

    Parameters
    ----------
    transfers : pd.DataFrame
        See `loaders.get_coders_transfers` (negative: from `region_1` to `region_2`).
    provinces : list[CANOEProvince]
        Provinces modelled.

    Returns
    -------
    pd.DataFrame
        Columns `region` (`CANOEProvince`), `outside` (code of the outside region,
        e.g. `USA`), `hour`, `outflow` and `inflow` (MWh).

    Examples
    --------
    >>> transfers = pd.DataFrame(
    ...     {"region_1": ["ON", "ON", "ON", "ON"], "region_2": ["USA", "USA", "QC", "QC"],
    ...      "hour": [0, 1, 0, 1], "transfer": [-100.0, 20.0, -5.0, 5.0]}
    ... )
    >>> boundary_flows(transfers, [CANOEProvince.ONTARIO])[["outside", "hour", "outflow", "inflow"]]
      outside  hour  outflow  inflow
    0      QC     0      5.0     0.0
    1      QC     1      0.0     5.0
    2     USA     0    100.0     0.0
    3     USA     1      0.0    20.0
    """
    modelled = {p.short(): p for p in provinces}
    first_inside = transfers["region_1"].isin(modelled)
    second_inside = transfers["region_2"].isin(modelled)
    boundary = transfers.loc[first_inside != second_inside]
    from_first = boundary["region_1"].isin(modelled)
    # Negative transfers go from region_1 to region_2
    leaving_first = (-boundary["transfer"]).clip(lower=0)
    entering_first = boundary["transfer"].clip(lower=0)
    flows = pd.DataFrame(
        {
            "region": boundary["region_1"].where(from_first, boundary["region_2"]),
            "outside": boundary["region_2"].where(from_first, boundary["region_1"]),
            "hour": boundary["hour"],
            "outflow": leaving_first.where(from_first, entering_first),
            "inflow": entering_first.where(from_first, leaving_first),
        }
    )
    summed = cast(
        pd.DataFrame, flows.groupby(["region", "outside", "hour"], as_index=False).sum()
    )
    return summed.assign(region=[modelled[code] for code in summed["region"]])


def _totals(
    flows: pd.DataFrame, column: str, how: str
) -> dict[tuple[CANOEProvince, str], float]:
    """`how` (`sum` or `max`) of `column` by (region, outside region)"""
    grouped = flows.groupby(["region", "outside"], sort=False)[column]
    totals = cast(pd.Series, grouped.sum() if how == "sum" else grouped.max())
    return {
        cast(tuple[CANOEProvince, str], key): float(value)
        for key, value in totals.items()
    }


def export_demands(flows: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """
    Electricity leaving each province to each outside region (PJ), the historical
    year repeated in every period, where any leaves.

    Parameters
    ----------
    flows : pd.DataFrame
        See `boundary_flows`.
    periods : list[int]
        Model periods.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `outside`, `period` and `demand`.
    """
    MWH_TO_PJ = 3.6e-6
    return pd.DataFrame(
        [
            {"region": r, "outside": o, "period": p, "demand": total * MWH_TO_PJ}
            for (r, o), total in _totals(flows, "outflow", "sum").items()
            if total > 0
            for p in periods
        ],
        columns=["region", "outside", "period", "demand"],
    )


def export_profiles(flows: pd.DataFrame) -> pd.DataFrame:
    """
    Share of the year's outflow of each province to each outside region in each hour,
    where any leaves.

    Returns columns `region`, `outside`, `hour` and `share`.
    """
    totals = _totals(flows, "outflow", "sum")
    total = np.array([totals[k] for k in zip(flows["region"], flows["outside"])])
    leaving = total > 0
    return pd.DataFrame(
        {
            "region": flows["region"].to_numpy()[leaving],
            "outside": flows["outside"].to_numpy()[leaving],
            "hour": flows["hour"].to_numpy()[leaving],
            "share": flows["outflow"].to_numpy()[leaving] / total[leaving],
        }
    )


def import_capacities(flows: pd.DataFrame) -> pd.DataFrame:
    """
    Capacity (GW) of the electricity entering each province from each outside region:
    its largest hourly inflow, where any enters.

    Returns columns `region`, `outside` and `capacity`.
    """
    MWH_PER_HOUR_TO_GW = 1e-3
    return pd.DataFrame(
        [
            {"region": r, "outside": o, "capacity": largest * MWH_PER_HOUR_TO_GW}
            for (r, o), largest in _totals(flows, "inflow", "max").items()
            if largest > 0
        ],
        columns=["region", "outside", "capacity"],
    )


def import_capacity_factors(flows: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """
    Hourly capacity factor of the electricity entering each province from each
    outside region: the inflow over the largest hourly inflow; below `tolerance`, 0.
    Where any enters.

    Returns columns `region`, `outside`, `hour` and `factor`.
    """
    largests = _totals(flows, "inflow", "max")
    largest = np.array([largests[k] for k in zip(flows["region"], flows["outside"])])
    entering = largest > 0
    factor = flows["inflow"].to_numpy()[entering] / largest[entering]
    return pd.DataFrame(
        {
            "region": flows["region"].to_numpy()[entering],
            "outside": flows["outside"].to_numpy()[entering],
            "hour": flows["hour"].to_numpy()[entering],
            "factor": np.where(factor < tolerance, 0.0, factor),
        }
    )

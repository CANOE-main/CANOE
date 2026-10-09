"""
Hourly capacity factors of the existing generators that follow the weather (wind,
solar, hydro), from the output of one weather year, 8760 hours in EST.

Ontario has measured output by generator (IESO); the other provinces' profiles are
synthesized:

- wind and solar: renewables.ninja at each facility, capacity-weighted, scaled to
  the facilities' CODERS annual energy;
- hydro: StatCan monthly hydro generation, flat within each month, shared between
  the hydro types by their CODERS annual energy.

Run-of-river, wind and solar get hourly capacity factors; reservoir hydro (daily and
monthly) a limit on each day's average, so the reservoir can shift the water within
the day (and, for monthly hydro, across days).
"""

import numpy as np
import pandas as pd

from canoe.common import CANOEProvince

from ..catalogue import GenerationTechnology


def existing_capacity_factors(
    fleet: pd.DataFrame,
    units: pd.DataFrame,
    output_by_fuel: pd.DataFrame,
    generator_output: pd.DataFrame,
    hydro_types: pd.DataFrame,
    monthly_hydro: pd.DataFrame,
    facility_profiles: pd.DataFrame,
    ieso_year: int,
    statcan_year: int,
    tolerance: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Hourly capacity factors of the existing wind, solar and run-of-river, and daily
    limits of the existing reservoir hydro, in the regions where the fleet has them;
    those below `tolerance` set to 0.

    Ontario takes IESO's measured output; the other provinces renewables.ninja (wind
    and solar) and StatCan (hydro), see the module docstring.

    Parameters
    ----------
    fleet : pd.DataFrame
        See `fleet.existing_generators`.
    units : pd.DataFrame
        The units of the groups in `fleet`, see `fleet.existing_units`.
    output_by_fuel, generator_output, hydro_types, monthly_hydro, facility_profiles :
        See `loaders.get_ieso_output_by_fuel`, `loaders.get_ieso_generator_output`,
        `loaders.get_ieso_hydro_types`, `loaders.get_statcan_monthly_hydro` and
        `loaders.get_renewables_ninja_facility_profiles`.
    ieso_year, statcan_year : int
        Years of the IESO and StatCan data.
    tolerance : float
        Smallest capacity factor kept (noise in the data).

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Hourly capacity factors (columns `region`, `technology`, `hour`, `factor`)
        and daily limits (`region`, `technology`, `day`, `factor`).

    Raises
    ------
    ValueError
        If Ontario has monthly reservoir hydro (IESO data has no such type).
    """
    ON = CANOEProvince.ONTARIO
    VRE = (
        GenerationTechnology.SolarPV,
        GenerationTechnology.WindOnshore,
        GenerationTechnology.WindOffshore,
    )
    HOURLY_HYDRO = (GenerationTechnology.HydroRunOfRiver,)
    DAILY_HYDRO = (GenerationTechnology.HydroDaily, GenerationTechnology.HydroMonthly)

    present = fleet[["region", "technology"]].drop_duplicates()
    in_ontario = list(dict.fromkeys(present.loc[present["region"] == ON, "technology"]))
    if GenerationTechnology.HydroMonthly in in_ontario:
        raise ValueError("Ontario monthly reservoir hydro has no IESO data")
    elsewhere = fleet.loc[fleet["region"] != ON]

    # Wind and solar
    ontario_vre = ontario_vre_capacity_factors(output_by_fuel, units, ieso_year)
    ontario_vre = ontario_vre.loc[ontario_vre["technology"].isin(in_ontario)].assign(
        region=ON
    )
    other_vre = facility_vre_capacity_factors(
        units.loc[(units["region"] != ON) & units["technology"].isin(VRE)],
        facility_profiles,
    )

    # Hydro
    ontario_hydro = ontario_hydro_capacity_factors(generator_output, hydro_types)
    ontario_hydro = ontario_hydro.loc[
        ontario_hydro["technology"].isin(in_ontario)
    ].assign(region=ON)
    other_hydro = statcan_hydro_capacity_factors(
        monthly_hydro,
        elsewhere.loc[elsewhere["technology"].isin(HOURLY_HYDRO + DAILY_HYDRO)],
        statcan_year,
    )
    hydro = _concat(
        [ontario_hydro, other_hydro], ["region", "technology", "hour", "factor"]
    )

    columns = ["region", "technology", "hour", "factor"]
    hourly = _concat(
        [
            ontario_vre[columns],
            other_vre,
            hydro.loc[hydro["technology"].isin(HOURLY_HYDRO), columns],
        ],
        columns,
    )
    daily = daily_capacity_factors(
        hydro.loc[hydro["technology"].isin(DAILY_HYDRO), columns]
    )
    return drop_below(hourly, tolerance), drop_below(daily, tolerance)


def ontario_vre_capacity_factors(
    output_by_fuel: pd.DataFrame, units: pd.DataFrame, year: int
) -> pd.DataFrame:
    """
    Hourly capacity factor of Ontario's wind and solar: the IESO hourly output of the
    fuel, scaled so its average is the CODERS capacity-weighted average capacity
    factor of the units over 20 MW running in `year` (those IESO reports), clipped to
    [0, 1]. Offshore wind takes the wind profile.

    Parameters
    ----------
    output_by_fuel : pd.DataFrame
        See `loaders.get_ieso_output_by_fuel`.
    units : pd.DataFrame
        See `fleet.existing_units`.
    year : int
        Year of the output.

    Returns
    -------
    pd.DataFrame
        Columns `technology`, `hour` and `factor`.

    Examples
    --------
    >>> output = pd.DataFrame(
    ...     {"hour": [0, 1], "fuel": ["WIND", "WIND"], "output": [100.0, 300.0]}
    ... )
    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ONTARIO] * 2,
    ...         "technology": [GenerationTechnology.WindOnshore] * 2,
    ...         "capacity": [100.0, 300.0],
    ...         "capacity_factor": [0.2, 0.4],
    ...         "start_year": [2010, 2015],
    ...     }
    ... )
    >>> ontario_vre_capacity_factors(output, units, 2018)["factor"].round(3).tolist()
    [0.175, 0.525]
    """
    MIN_REPORTED_MW = 20
    FUELS = {
        GenerationTechnology.SolarPV: "SOLAR",
        GenerationTechnology.WindOnshore: "WIND",
        GenerationTechnology.WindOffshore: "WIND",
    }
    reported = units.loc[
        (units["region"] == CANOEProvince.ONTARIO)
        & (units["start_year"] <= year)
        & (units["capacity"] >= MIN_REPORTED_MW)
    ]
    frames: list[pd.DataFrame] = []
    for technology, fuel in FUELS.items():
        of_units = reported.loc[reported["technology"] == technology]
        hourly = output_by_fuel.loc[output_by_fuel["fuel"] == fuel].sort_values("hour")
        if of_units.empty or hourly.empty:
            continue
        annual = float(
            (of_units["capacity_factor"] * of_units["capacity"]).sum()
            / of_units["capacity"].sum()
        )
        profile = hourly["output"].to_numpy(dtype=float)
        frames.append(
            pd.DataFrame(
                {
                    "technology": technology,
                    "hour": hourly["hour"].to_numpy(),
                    "factor": np.clip(profile / profile.mean() * annual, 0, 1),
                }
            )
        )
    return _concat(frames, ["technology", "hour", "factor"])


def facility_vre_capacity_factors(
    units: pd.DataFrame, profiles: pd.DataFrame
) -> pd.DataFrame:
    """
    Hourly capacity factor of the wind and solar of each region: the renewables.ninja
    profiles of its facilities weighted by capacity, scaled so the year's output is
    the units' CODERS annual energy, clipped to [0, 1].

    Parameters
    ----------
    units : pd.DataFrame
        The wind and solar units, see `fleet.existing_units` (columns `region`,
        `technology`, `facility_code`, `capacity` in MW, `annual_energy` in GWh).
    profiles : pd.DataFrame
        See `loaders.get_renewables_ninja_facility_profiles`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `hour` and `factor`.

    Raises
    ------
    ValueError
        If a facility has no profile.

    Examples
    --------
    Two facilities of 100 and 300 MW producing 438 GWh a year (a capacity factor of
    0.125):

    >>> units = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ALBERTA] * 2,
    ...         "technology": [GenerationTechnology.WindOnshore] * 2,
    ...         "facility_code": ["A", "B"],
    ...         "capacity": [100.0, 300.0],
    ...         "annual_energy": [219.0, 219.0],
    ...     }
    ... )
    >>> profiles = pd.DataFrame({"A": [0.4] * 8760, "B": [0.2] * 8760})
    >>> facility_vre_capacity_factors(units, profiles)["factor"].round(3).unique()
    array([0.125])
    """
    MWH_PER_GWH = 1e3

    missing = sorted(set(units["facility_code"]) - set(profiles.columns))
    if missing:
        raise ValueError(f"renewables.ninja: no profile for facilities {missing}")
    frames: list[pd.DataFrame] = []
    pairs = units[["region", "technology"]].drop_duplicates()
    for region, technology in zip(pairs["region"], pairs["technology"]):
        of_units = units.loc[
            (units["region"] == region) & (units["technology"] == technology)
        ]
        capacity = of_units["capacity"].to_numpy(dtype=float)
        # Hourly output (MWh) of the facilities at their profiles
        output = profiles[of_units["facility_code"].tolist()].to_numpy() @ capacity
        energy = of_units["annual_energy"].to_numpy(dtype=float).sum() * MWH_PER_GWH
        factor = output * energy / output.sum() / capacity.sum()
        frames.append(
            pd.DataFrame(
                {
                    "region": region,
                    "technology": technology,
                    "hour": np.arange(len(factor)),
                    "factor": np.clip(factor, 0, 1),
                }
            )
        )
    return _concat(frames, ["region", "technology", "hour", "factor"])


def ontario_hydro_capacity_factors(
    generator_output: pd.DataFrame, hydro_types: pd.DataFrame
) -> pd.DataFrame:
    """
    Hourly capacity factor of Ontario's run-of-river and daily-reservoir hydro: the
    IESO output of the generators of each type over their available capacity (0
    where none is available), clipped to [0, 1] (output can exceed the reported
    capability).

    Parameters
    ----------
    generator_output : pd.DataFrame
        See `loaders.get_ieso_generator_output`.
    hydro_types : pd.DataFrame
        See `loaders.get_ieso_hydro_types`.

    Returns
    -------
    pd.DataFrame
        Columns `technology`, `hour` and `factor`.

    Examples
    --------
    >>> output = pd.DataFrame(
    ...     {
    ...         "hour": [0, 0, 1, 1],
    ...         "generator": ["A", "B", "A", "B"],
    ...         "output": [5.0, 10.0, 0.0, 20.0],
    ...         "capability": [10.0, 10.0, 10.0, 30.0],
    ...     }
    ... )
    >>> types = pd.DataFrame(
    ...     {"generator": ["A", "B"], "technology": [GenerationTechnology.HydroRunOfRiver] * 2}
    ... )
    >>> ontario_hydro_capacity_factors(output, types)["factor"].tolist()
    [0.75, 0.5]
    """
    typed = generator_output.merge(hydro_types, on="generator", how="inner")
    totals = typed.groupby(["technology", "hour"], sort=False, as_index=False).agg(
        output=("output", "sum"), capability=("capability", "sum")
    )
    capability = np.asarray(totals["capability"], dtype=float)
    output = np.asarray(totals["output"], dtype=float)
    return pd.DataFrame(
        {
            "technology": totals["technology"],
            "hour": totals["hour"],
            "factor": np.clip(
                np.divide(
                    output, capability, out=np.zeros_like(output), where=capability > 0
                ),
                0,
                1,
            ),
        }
    )


def statcan_hydro_capacity_factors(
    monthly: pd.DataFrame, fleet: pd.DataFrame, year: int
) -> pd.DataFrame:
    """
    Hourly capacity factor of the hydro of each region: the StatCan monthly hydro
    generation, flat over the hours of the month, shared between the region's hydro
    types by their CODERS annual energy, over each type's capacity, clipped to
    [0, 1].

    Parameters
    ----------
    monthly : pd.DataFrame
        See `loaders.get_statcan_monthly_hydro`.
    fleet : pd.DataFrame
        The hydro of the regions, see `fleet.existing_generators` (`capacity` in GW).
    year : int
        Year of the generation (for the days of each month).

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `hour` and `factor`.

    Examples
    --------
    3,720 GWh in a 31-day January (5 GW on average) shared by two types with equal
    annual energy, each of 5 GW: a capacity factor of 0.5 every hour of January.

    >>> monthly = pd.DataFrame(
    ...     {"region": [CANOEProvince.QUEBEC] * 12, "month": range(1, 13),
    ...      "generation": [3_720_000.0] + [0.0] * 11}
    ... )
    >>> fleet = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.QUEBEC] * 2,
    ...         "technology": [GenerationTechnology.HydroDaily, GenerationTechnology.HydroRunOfRiver],
    ...         "capacity": [5.0, 5.0],
    ...         "annual_energy": [10.0, 10.0],
    ...     }
    ... )
    >>> factors = statcan_hydro_capacity_factors(monthly, fleet, 2018)
    >>> [(t.value, s) for t, s in factors.groupby("technology")["factor"].sum().round(3).items()]
    [('hydro_daily', 372.0), ('hydro_run', 372.0)]
    >>> float(factors["factor"].max())
    0.5
    """
    HOURS = 8760
    MW_TO_GW = 1e-3

    timestamps = pd.Series(pd.date_range(f"{year}-01-01", periods=HOURS, freq="h"))
    month_of_hour = timestamps.dt.month.to_numpy()
    hours_in_month = np.bincount(month_of_hour, minlength=13)

    frames: list[pd.DataFrame] = []
    for region in dict.fromkeys(fleet["region"]):
        of_region = fleet.loc[fleet["region"] == region]
        generation = monthly.loc[monthly["region"] == region].set_index("month")[
            "generation"
        ]
        # Average output (GW) in each hour: the month's generation spread evenly
        average = (
            generation.reindex(range(1, 13), fill_value=0.0).to_numpy()
            / hours_in_month[1:]
            * MW_TO_GW
        )[month_of_hour - 1]
        total_energy = of_region["annual_energy"].to_numpy(dtype=float).sum()
        for technology in dict.fromkeys(of_region["technology"]):
            of_type = of_region.loc[of_region["technology"] == technology]
            share = of_type["annual_energy"].to_numpy(dtype=float).sum() / total_energy
            capacity = of_type["capacity"].to_numpy(dtype=float).sum()
            factor = average * share / capacity
            frames.append(
                pd.DataFrame(
                    {
                        "region": region,
                        "technology": technology,
                        "hour": np.arange(HOURS),
                        "factor": np.clip(factor, 0, 1),
                    }
                )
            )
    return _concat(frames, ["region", "technology", "hour", "factor"])


def daily_capacity_factors(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Average capacity factor of each day (0-364) from hourly ones, keeping the other
    columns.

    Examples
    --------
    >>> hourly = pd.DataFrame({"hour": range(48), "factor": [0.2] * 24 + [0.6] * 24})
    >>> daily_capacity_factors(hourly)
       day  factor
    0    0     0.2
    1    1     0.6
    """
    keys = [c for c in hourly.columns if c not in ("hour", "factor")]
    days = hourly.assign(day=hourly["hour"] // 24)
    return pd.DataFrame(
        days.groupby([*keys, "day"], sort=False, as_index=False).agg(
            factor=("factor", "mean")
        )
    )


def drop_below(factors: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """
    Capacity factors below `tolerance` set to 0 (noise in the data).

    Examples
    --------
    >>> drop_below(pd.DataFrame({"factor": [0.005, 0.5]}), 0.01)["factor"].tolist()
    [0.0, 0.5]
    """
    return factors.assign(
        factor=factors["factor"].mask(factors["factor"] < tolerance, 0.0)
    )


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    """`frames` concatenated, or an empty frame with `columns`"""
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)

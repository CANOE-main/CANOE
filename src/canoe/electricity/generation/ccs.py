"""
Parameters of carbon capture: the CCS retrofits of coal and natural gas combined
cycle generators, and the CO2 captured by them and by the generators built with
capture.

A retrofitted generator's output goes to an intermediate commodity, from which a free
bypass or a retrofit takes it to the grid. The retrofit loses part of the electricity
(ATB net output penalty) and captures part of the CO2 the fuel would emit.

Captured CO2 is written as negative emissions: the fuel module accounts the combustion
emissions of every fuel burned, with the shared combustion factors
(`common.loaders.get_combustion_emission_factors`), and capture subtracts its share.
"""

import numpy as np
import pandas as pd

from canoe.common import CANOEEmission, CANOEFuel, CANOEProvince, CANOESector

from ..catalogue import CCSRetrofit, GenerationTechnology
from .parameters import atb_value


def retrofit_processes(
    fleet: pd.DataFrame,
    retrofits: list[CCSRetrofit],
    new_technologies: list[GenerationTechnology],
    provinces: list[CANOEProvince],
    projection_years: dict[int, int],
    lifetimes: dict[GenerationTechnology, int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Where and when each retrofit can be built, and the bypass of each retrofitted
    generator.

    A retrofit can be built in a region and period (its vintage) if a generator it
    applies to lives there then: an existing vintage of the fleet, or a new one if
    the generator is a new technology (all provinces, every period). It lives the
    generator's lifetime, but never past the end of life of the last of those
    generators (it would have nothing left to treat). The bypass, one vintage (the
    first period), lives until that end of life too.

    Parameters
    ----------
    fleet : pd.DataFrame
        Existing generators, see `fleet.existing_generators` (empty if left out).
    retrofits : list[CCSRetrofit]
        Retrofits modelled.
    new_technologies : list[GenerationTechnology]
        New generators modelled.
    provinces : list[CANOEProvince]
        Regions modelled.
    projection_years : dict[int, int]
        Period -> ATB year of the vintages, see
        `common.periods.projection_year_by_period`.
    lifetimes : dict[GenerationTechnology, int]
        See `generation.parameters.generation_lifetimes`.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Retrofit processes (columns `region`, `technology` (`CCSRetrofit`),
        `vintage`, `atb_year`, `lifetime`) and bypasses (`region`, `generator`,
        `lifetime`).

    Examples
    --------
    Ontario coal of vintages 1990 and 2000 (45-year life): the last retires in 2045,
    so a 2030 retrofit lives 15 years:

    >>> COAL = GenerationTechnology.Coal
    >>> fleet = pd.DataFrame(
    ...     {"region": [CANOEProvince.ONTARIO] * 2, "technology": [COAL] * 2,
    ...      "vintage": [1990, 2000]}
    ... )
    >>> processes, bypasses = retrofit_processes(
    ...     fleet, [CCSRetrofit.Coal90], [], [CANOEProvince.ONTARIO],
    ...     {2025: 2030, 2030: 2035, 2035: 2040, 2040: 2045, 2045: 2050}, {COAL: 45},
    ... )
    >>> processes[["vintage", "lifetime"]].values.tolist()
    [[2025, 20], [2030, 15], [2035, 10], [2040, 5]]
    >>> bypasses["lifetime"].tolist()
    [20]
    """
    periods = list(projection_years)
    process_rows: list[dict[str, object]] = []
    bypass_rows: list[dict[str, object]] = []
    for generator in dict.fromkeys(r.get_generator() for r in retrofits):
        life = lifetimes[generator]
        # Vintages of the generator in each region, existing and new
        vintages: dict[CANOEProvince, list[int]] = {}
        of_fleet = fleet.loc[fleet["technology"] == generator]
        for region, vintage in zip(of_fleet["region"], of_fleet["vintage"]):
            vintages.setdefault(region, []).append(int(vintage))
        if generator in new_technologies:
            for region in provinces:
                vintages.setdefault(region, []).extend(periods)

        for region in [p for p in CANOEProvince if p in vintages]:
            end_of_life = max(v + life for v in vintages[region])
            bypass_rows.append(
                {
                    "region": region,
                    "generator": generator,
                    "lifetime": end_of_life - periods[0],
                }
            )
            for retrofit in [r for r in retrofits if r.get_generator() == generator]:
                for vintage in periods:
                    if not any(v <= vintage < v + life for v in vintages[region]):
                        continue
                    process_rows.append(
                        {
                            "region": region,
                            "technology": retrofit,
                            "vintage": vintage,
                            "atb_year": projection_years[vintage],
                            "lifetime": min(life, end_of_life - vintage),
                        }
                    )
    return (
        pd.DataFrame(
            process_rows,
            columns=["region", "technology", "vintage", "atb_year", "lifetime"],
        ),
        pd.DataFrame(bypass_rows, columns=["region", "generator", "lifetime"]),
    )


def retrofit_efficiencies(processes: pd.DataFrame, atb: pd.DataFrame) -> pd.DataFrame:
    """
    Electricity out of each retrofit per unit of the generator's electricity in: 1
    plus the ATB net output penalty (negative) at the process's ATB year.

    Returns columns `region`, `technology`, `vintage` and `efficiency`.

    Examples
    --------
    >>> processes = pd.DataFrame(
    ...     {"region": [CANOEProvince.ALBERTA], "technology": [CCSRetrofit.Coal90],
    ...      "vintage": [2025], "atb_year": [2030]}
    ... )
    >>> atb = pd.DataFrame(
    ...     {"display_name": ["Coal integrated retrofit 90%-CCS"],
    ...      "parameter": ["Net Output Penalty"], "year": [2030], "value": [-0.222]}
    ... )
    >>> retrofit_efficiencies(processes, atb)["efficiency"].tolist()
    [0.778]
    """
    return pd.DataFrame(
        {
            "region": processes["region"],
            "technology": processes["technology"],
            "vintage": processes["vintage"],
            "efficiency": [
                1 + atb_value(atb, t, "Net Output Penalty", y)
                for t, y in zip(processes["technology"], processes["atb_year"])
            ],
        }
    )


def retrofit_om_costs(
    processes: pd.DataFrame,
    atb: pd.DataFrame,
    periods: list[int],
    atb_conversion: float,
) -> pd.DataFrame:
    """
    Fixed and variable operation and maintenance costs of each retrofit, from the ATB
    at the process's ATB year, in the periods it lives (its own `lifetime`), in M$
    of the model currency. Zero costs are left out (NaN).

    Returns columns `region`, `technology`, `vintage`, `period`, `fixed`
    (M$/GW-year) and `variable` (M$/PJ).
    """
    PER_MWH_TO_PER_PJ = 1 / 3.6  # $/MWh -> M$/PJ

    rows: list[dict[str, object]] = []
    for region, retrofit, vintage, year, lifetime in zip(
        processes["region"],
        processes["technology"],
        processes["vintage"],
        processes["atb_year"],
        processes["lifetime"],
    ):
        # $/kW-year is M$/GW-year
        fixed = atb_value(atb, retrofit, "Fixed O&M", year) * atb_conversion
        variable = (
            atb_value(atb, retrofit, "Variable O&M", year)
            * PER_MWH_TO_PER_PJ
            * atb_conversion
        )
        for period in periods:
            if vintage <= period < vintage + lifetime:
                rows.append(
                    {
                        "region": region,
                        "technology": retrofit,
                        "vintage": vintage,
                        "period": period,
                        "fixed": fixed or np.nan,
                        "variable": variable or np.nan,
                    }
                )
    return pd.DataFrame(
        rows, columns=["region", "technology", "vintage", "period", "fixed", "variable"]
    )


def electricity_co2_factors(combustion_factors: pd.DataFrame) -> dict[CANOEFuel, float]:
    """
    CO2 of burning each fuel in the electricity sector (kt per PJ of fuel).

    Parameters
    ----------
    combustion_factors : pd.DataFrame
        See `common.loaders.get_combustion_emission_factors`.

    Examples
    --------
    >>> factors = pd.DataFrame(
    ...     {"sector": [CANOESector.Electricity, CANOESector.Industry],
    ...      "fuel": [CANOEFuel.Coal, CANOEFuel.Coal],
    ...      "emission": [CANOEEmission.CO2] * 2, "factor": [86.02, 90.0]}
    ... )
    >>> electricity_co2_factors(factors)
    {Coal: 86.02}
    """
    # Compared element by element: pandas compares string columns with `str()` of
    # the scalar, and `CANOESector`'s is its name, not its value
    return {
        fuel: float(factor)
        for sector, fuel, emission, factor in zip(
            combustion_factors["sector"],
            combustion_factors["fuel"],
            combustion_factors["emission"],
            combustion_factors["factor"],
        )
        if sector == CANOESector.Electricity and emission == CANOEEmission.CO2
    }


def generator_capture_factors(
    technologies: list[GenerationTechnology], co2_factors: dict[CANOEFuel, float]
) -> dict[GenerationTechnology, float]:
    """
    CO2 captured per unit of fuel burned (negative, kt/PJ of fuel) by the generators
    built with capture: capture rate × the fuel's CO2 factor.

    Raises
    ------
    ValueError
        If a capturing generator's fuel has no CO2 factor.

    Examples
    --------
    >>> generator_capture_factors(
    ...     [GenerationTechnology.CoalCCS, GenerationTechnology.Coal],
    ...     {CANOEFuel.Coal: 86.02},
    ... )
    {<GenerationTechnology.CoalCCS: 'coal_ccs'>: -81.719}
    """
    factors: dict[GenerationTechnology, float] = {}
    for technology in technologies:
        rate = technology.get_capture_rate()
        fuel = technology.get_input_fuel()
        if rate == 0 or fuel is None:
            continue
        if fuel not in co2_factors:
            raise ValueError(f"No CO2 combustion factor for {fuel} (electricity)")
        factors[technology] = -rate * co2_factors[fuel]
    return factors


def retrofit_capture_factors(
    retrofits: list[CCSRetrofit],
    co2_factors: dict[CANOEFuel, float],
    heat_rates: dict[GenerationTechnology, float],
) -> dict[CCSRetrofit, float]:
    """
    CO2 captured by each retrofit per unit of the generator's electricity it takes
    (negative, kt/PJ): capture rate × the fuel's CO2 factor × the fuel the generator
    burns per unit of electricity (its assumed heat rate).

    Parameters
    ----------
    heat_rates : dict[GenerationTechnology, float]
        MMBtu of fuel per MWh, see `GenerationConfig.ccs_retrofit_heat_rates`.

    Examples
    --------
    A heat rate of 8.49 MMBtu/MWh is 2.488 PJ of coal per PJ of electricity:

    >>> factors = retrofit_capture_factors(
    ...     [CCSRetrofit.Coal90], {CANOEFuel.Coal: 86.02}, {GenerationTechnology.Coal: 8.49}
    ... )
    >>> round(factors[CCSRetrofit.Coal90], 2)
    -192.63
    """
    MWH_PER_MMBTU = 0.29307107

    factors: dict[CCSRetrofit, float] = {}
    for retrofit in retrofits:
        generator = retrofit.get_generator()
        fuel = generator.get_input_fuel()
        if fuel is None or fuel not in co2_factors:
            raise ValueError(f"No CO2 combustion factor for {fuel} (electricity)")
        fuel_per_output = heat_rates[generator] * MWH_PER_MMBTU
        factors[retrofit] = (
            -retrofit.get_capture_rate() * co2_factors[fuel] * fuel_per_output
        )
    return factors

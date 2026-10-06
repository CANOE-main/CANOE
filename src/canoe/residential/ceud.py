"""
Residential energy use, stock and efficiencies of each province from the NRCan CEUD
residential tables, as tidy frames. Nothing in here touches the database.

Labels (systems, sources, appliances, building types) are NRCan's, as returned by the
loaders (see `loaders`); percentages are turned into fractions.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince

from .loaders import (
    get_ceud_appliance_energy_use,
    get_ceud_appliance_stock,
    get_ceud_cooling_systems,
    get_ceud_heating_system_efficiencies,
    get_ceud_heating_system_stock,
    get_ceud_household_shares,
    get_ceud_lighting_energy_use,
    get_ceud_space_cooling_energy_use,
    get_ceud_space_heating_energy_use,
    get_ceud_water_heater_stock,
    get_ceud_water_heating_energy_use,
)


@dataclass(frozen=True)
class ResidentialCEUD:
    """
    The CEUD residential data of the modelled provinces, in the data year (cooling
    efficiencies: every year). Every frame has a `province` column.

    Parameters
    ----------
    lighting_energy_use : pd.DataFrame
        `energy_use` (PJ).
    space_heating_energy_use : pd.DataFrame
        `system` (heating system type), `energy_use` (PJ).
    space_cooling_energy_use : pd.DataFrame
        `system` ("room", "central"), `energy_use` (PJ).
    water_heating_energy_use : pd.DataFrame
        `source` (energy source), `energy_use` (PJ).
    appliance_energy_use : pd.DataFrame
        `appliance`, `energy_use` (PJ).
    household_shares : pd.DataFrame
        `building_type`, `share` (fraction of households).
    heating_system_stock : pd.DataFrame
        `system`, `stock` (thousands).
    heating_system_efficiencies : pd.DataFrame
        `system`, `fuel` (for dual systems, else None), `efficiency` (fraction).
    cooling_system_stock : pd.DataFrame
        `system`, `stock` (thousands).
    cooling_system_efficiencies : pd.DataFrame
        `system`, `kind` ("new unit", "stock"), `metric` ("EER", "SEER"), `year`,
        `efficiency` (in the metric).
    water_heater_stock : pd.DataFrame
        `source`, `stock` (thousands).
    appliance_stock : pd.DataFrame
        `appliance`, `fuel` ("electricity", "natural gas"), `stock` (thousands).
    """

    lighting_energy_use: pd.DataFrame
    space_heating_energy_use: pd.DataFrame
    space_cooling_energy_use: pd.DataFrame
    water_heating_energy_use: pd.DataFrame
    appliance_energy_use: pd.DataFrame
    household_shares: pd.DataFrame
    heating_system_stock: pd.DataFrame
    heating_system_efficiencies: pd.DataFrame
    cooling_system_stock: pd.DataFrame
    cooling_system_efficiencies: pd.DataFrame
    water_heater_stock: pd.DataFrame
    appliance_stock: pd.DataFrame


def load_ceud_tables(provinces: list[CANOEProvince], data_year: int) -> ResidentialCEUD:
    """The CEUD residential tables of `provinces`, each read once, see
    `ResidentialCEUD`."""

    def by_label(
        get: Callable[[CANOEProvince, int], pd.Series], label: str, value: str
    ) -> pd.DataFrame:
        """A loader's series (values by label) of every province, one row each"""
        frames = [
            pd.DataFrame({"province": p, label: series.index, value: series.to_numpy()})
            for p in provinces
            for series in [get(p, data_year)]
        ]
        return pd.concat(frames, ignore_index=True)

    def with_province(frames: dict[CANOEProvince, pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(
            [
                df.assign(province=p).reindex(columns=["province", *df.columns])
                for p, df in frames.items()
            ],
            ignore_index=True,
        )

    heating_efficiencies = with_province(
        {p: get_ceud_heating_system_efficiencies(p, data_year) for p in provinces}
    )
    household_shares = by_label(get_ceud_household_shares, "building_type", "share")
    cooling = {p: get_ceud_cooling_systems(p, data_year) for p in provinces}
    return ResidentialCEUD(
        lighting_energy_use=pd.DataFrame(
            {
                "province": provinces,
                "energy_use": [
                    get_ceud_lighting_energy_use(p, data_year) for p in provinces
                ],
            }
        ),
        space_heating_energy_use=by_label(
            get_ceud_space_heating_energy_use, "system", "energy_use"
        ),
        space_cooling_energy_use=by_label(
            get_ceud_space_cooling_energy_use, "system", "energy_use"
        ),
        water_heating_energy_use=by_label(
            get_ceud_water_heating_energy_use, "source", "energy_use"
        ),
        appliance_energy_use=by_label(
            get_ceud_appliance_energy_use, "appliance", "energy_use"
        ),
        household_shares=household_shares.assign(share=household_shares["share"] / 100),
        heating_system_stock=by_label(get_ceud_heating_system_stock, "system", "stock"),
        heating_system_efficiencies=heating_efficiencies.assign(
            efficiency=heating_efficiencies["efficiency"] / 100
        ),
        cooling_system_stock=by_label(lambda p, _: cooling[p].stock, "system", "stock"),
        cooling_system_efficiencies=with_province(
            {p: cooling[p].efficiencies for p in provinces}
        ),
        water_heater_stock=by_label(get_ceud_water_heater_stock, "source", "stock"),
        appliance_stock=with_province(
            {p: get_ceud_appliance_stock(p, data_year) for p in provinces}
        ),
    )


def ceud_fuel(label: str) -> CANOEFuel:
    """
    The fuel of a CEUD energy source label (dual heating systems, appliance stock).

    Examples
    --------
    >>> ceud_fuel("heating oil")
    Oil
    """
    FUELS: dict[str, CANOEFuel] = {
        "electricity": CANOEFuel.Electricity,
        "natural gas": CANOEFuel.NaturalGas,
        "heating oil": CANOEFuel.Oil,
        "wood": CANOEFuel.Wood,
    }
    return FUELS[label]

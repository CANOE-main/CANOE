"""
Combustion emission factors of the commercial fuels, from the US EPA GHG Emission
Factors Hub (stationary combustion), as in the previous version.
"""

import pandas as pd

from canoe.common import CANOEEmission, CANOEFuel, GoldConnectorConfig

from .loaders import get_epa_emission_factors_table

# EPA fuel used for each commercial fuel; fuels left out (electricity) do not emit
_EPA_FUELS: dict[CANOEFuel, str] = {
    CANOEFuel.NaturalGas: "Natural Gas",
    CANOEFuel.Oil: "Distillate Fuel Oil No. 2",
}

# EPA column and its conversion to kt per PJ of fuel (1 mmBtu = 1.055056 GJ)
_MMBTU_PER_PJ = 1e6 / 1.055056
_EPA_COLUMNS: dict[CANOEEmission, tuple[str, float]] = {
    CANOEEmission.CO2: ("CO2 Factor", _MMBTU_PER_PJ * 1e-6),  # kg/mmBtu
    CANOEEmission.CH4: ("CH4 Factor", _MMBTU_PER_PJ * 1e-9),  # g/mmBtu
    CANOEEmission.N2O: ("N2O Factor", _MMBTU_PER_PJ * 1e-9),  # g/mmBtu
}


def load_combustion_emission_factors(
    data_cache_config: GoldConnectorConfig,
) -> dict[CANOEEmission, dict[CANOEFuel, float]]:
    """
    Emissions of each gas per unit of fuel burned (kt/PJ), for the fuels with an EPA
    equivalent (see `_EPA_FUELS`).
    """
    table = _clean_epa_table(get_epa_emission_factors_table(data_cache_config))
    return {
        emission: {
            fuel: float(table.loc[epa_fuel, column]) * to_kt_per_pj
            for fuel, epa_fuel in _EPA_FUELS.items()
        }
        for emission, (column, to_kt_per_pj) in _EPA_COLUMNS.items()
    }


def describe_epa_fuels() -> str:
    """Which EPA fuel is used for each commercial fuel, for notes"""
    return ", ".join(
        f"{epa_fuel} for {fuel.get_desc_name()}"
        for fuel, epa_fuel in _EPA_FUELS.items()
    )


def _clean_epa_table(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Keep the fuel rows (with a numeric CO2 factor) of the per-mmBtu factors, indexed by
    fuel, as floats. Section and unit header rows are dropped.
    """
    columns = [column for column, _ in _EPA_COLUMNS.values()]
    table = raw[["Fuel Type", *columns]]
    numeric = pd.to_numeric(table["CO2 Factor"], errors="coerce").notna()  # pyright: ignore[reportAttributeAccessIssue]
    table = table[numeric].set_index("Fuel Type")
    return table.astype(float)

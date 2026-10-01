"""
Loaders for the cached datasets used only by the industry sector.

Each function reads a single dataset and is the only place that knows its path and
layout (file names, row labels, missing-value markers), so when the cache changes
shape the error points to the function to fix. They return tidy frames; everything
downstream is independent of the source layout.
"""

from canoe.common import CANOEFuel

CEUD_INDUSTRY_SOURCES: dict[str, CANOEFuel] = {
    "Electricity": CANOEFuel.Electricity,
    "Natural Gas": CANOEFuel.NaturalGas,
    "Diesel Fuel Oil, Light Fuel Oil and Kerosene": CANOEFuel.Diesel,
    "Heavy Fuel Oil": CANOEFuel.HeavyFuelOil,
    "Still Gas and Petroleum Coke": CANOEFuel.PetroleumCoke,
    "LPG and Gas Plant NGL": CANOEFuel.NaturalGasLiquids,
    "Coal": CANOEFuel.Coal,
    "Coke and Coke Oven Gas": CANOEFuel.Coke,
    "Wood Waste and Pulping Liquor": CANOEFuel.Wood,
    "Other2": CANOEFuel.Other,
}
"""Energy sources of the NRCan CEUD industry tables (row labels, "Other2" with its
footnote mark) -> CANOE fuel. Every source has a CANOE fuel."""

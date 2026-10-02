"""
Fuel imports a sector declares to the fuel module (`CANOEFuelImport`), derived from
the technologies it builds so they always match the rows it writes.

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py`.
"""

from collections.abc import Iterable

from canoe.canoe_objects.technology import TechnologyEntity
from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.common.naming import get_fuel_commodity_in_sector


def declare_fuel_imports(
    sector: CANOESector, technologies: Iterable[TechnologyEntity]
) -> list[CANOEFuelImport]:
    """
    The fuels `technologies` take from `sector`, each with the provinces where some
    technology takes the sector's fuel commodity (e.g. `C_ng`) as input.

    Fuels are in order of first use; provinces in the order of `CANOEProvince`.
    Inputs that are not fuel commodities of the sector (e.g. a demand, or another
    sector's commodity) are ignored.

    Examples
    --------
    >>> from canoe.canoe_objects.array_types import RegionVintageArray
    >>> from canoe.common.naming import DatasetIdentifier
    >>> data_id = DatasetIdentifier(CANOESector.Commercial, "DOC", "001")
    >>> furnace = TechnologyEntity("C_NG_FRN", "C_D_DOC", data_id).with_efficiency(
    ...     "C_ng", RegionVintageArray([CANOEProvince.ONTARIO], [2025], fill=0.9)
    ... )
    >>> boiler = TechnologyEntity("C_OIL_BLR", "C_D_DOC", data_id).with_efficiency(
    ...     "C_oil", RegionVintageArray([CANOEProvince.NOVA_SCOTIA], [2025], fill=0.8)
    ... )
    >>> for fuel_import in declare_fuel_imports(CANOESector.Commercial, [furnace, boiler]):
    ...     print(fuel_import.fuel, [p.short() for p in fuel_import.provinces])
    NaturalGas ['ON']
    Oil ['NS']
    """
    fuel_of_commodity = {
        get_fuel_commodity_in_sector(sector, fuel): fuel for fuel in CANOEFuel
    }
    provinces_by_fuel: dict[CANOEFuel, set[CANOEProvince]] = {}
    for technology in technologies:
        for input_commodity in technology.inputs:
            fuel = fuel_of_commodity.get(input_commodity)
            if fuel is None:
                continue
            provinces_by_fuel.setdefault(fuel, set()).update(
                technology.input_regions(input_commodity)
            )
    return [
        CANOEFuelImport(
            sector=sector,
            fuel=fuel,
            provinces=tuple(p for p in CANOEProvince if p in provinces),
        )
        for fuel, provinces in provinces_by_fuel.items()
        if provinces
    ]

"""
Parameters of the storage: lifetimes and round-trip efficiencies. Costs are the
generators' (`generation.parameters.process_investment_costs`,
`process_om_costs`): NREL ATB where the technology has an equivalent, CODERS
otherwise.
"""

import pandas as pd

from ..catalogue import StorageTechnology


def storage_lifetimes(
    generic: pd.DataFrame, never_retiring_lifetime: int
) -> dict[StorageTechnology, int]:
    """
    Lifetime (years) of each storage technology: CODERS `service_life`, or, for
    pumped hydro, which never retires, one that reaches the end of the horizon.

    Parameters
    ----------
    generic : pd.DataFrame
        CODERS generic parameters, see `loaders.get_coders_generation_generic`.
    never_retiring_lifetime : int
        See `common.periods.never_retiring_lifetime`.

    Examples
    --------
    >>> generic = pd.DataFrame(
    ...     {"service_life": [15, 100]},
    ...     index=pd.Index(["storage_lithium", "storage_pump"], name="coders_type"),
    ... )
    >>> lifetimes = storage_lifetimes(generic, 26)
    >>> lifetimes[StorageTechnology.Battery2h], lifetimes[StorageTechnology.PumpedHydro4h]
    (15, 26)
    """
    return {
        technology: never_retiring_lifetime
        if technology.never_retires()
        else int(generic.loc[technology.get_coders_generic_type(), "service_life"])
        for technology in StorageTechnology
        if technology.get_coders_generic_type() in generic.index
    }


def storage_efficiencies(
    processes: pd.DataFrame, battery: float, pumped_hydro: float
) -> pd.DataFrame:
    """
    Round-trip efficiency of each storage process (electricity out per unit
    stored).

    Parameters
    ----------
    processes : pd.DataFrame
        Columns `region`, `technology` (`StorageTechnology`) and `vintage`.
    battery, pumped_hydro : float
        Round-trip efficiencies, see `StorageConfig`.

    Returns
    -------
    pd.DataFrame
        Columns `region`, `technology`, `vintage` and `efficiency`.

    Examples
    --------
    >>> from canoe.common import CANOEProvince
    >>> processes = pd.DataFrame(
    ...     {
    ...         "region": [CANOEProvince.ONTARIO] * 2,
    ...         "technology": [StorageTechnology.Battery4h, StorageTechnology.PumpedHydro4h],
    ...         "vintage": [2020, 2024],
    ...     }
    ... )
    >>> storage_efficiencies(processes, 0.85, 0.8)["efficiency"].tolist()
    [0.85, 0.8]
    """
    return pd.DataFrame(
        {
            "region": processes["region"],
            "technology": processes["technology"],
            "vintage": processes["vintage"],
            "efficiency": [
                pumped_hydro if t.is_pumped_hydro() else battery
                for t in processes["technology"]
            ],
        }
    )

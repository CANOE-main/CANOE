from pydantic import BaseModel, ConfigDict

from canoe.common import GlobalWarmingPotential


class EmissionsConfig(BaseModel):
    """
    Global emissions settings (`[compiler.base.emissions]`), shared by all modules.

    Examples
    --------
    >>> EmissionsConfig().gwp
    <GlobalWarmingPotential.AR5_100: 'AR5-100'>
    >>> EmissionsConfig.model_validate({"gwp": "AR5-100", "cost_of_co2e": 0.05}).cost_of_co2e
    0.05
    """

    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportUnannotatedClassAttribute]

    # Weights of the gases in the CO2-equivalent rows
    gwp: GlobalWarmingPotential = GlobalWarmingPotential.AR5_100
    # Cost of CO2-equivalent emissions in every region and model period (none by default)
    cost_of_co2e: float | None = None
    cost_units: str = "M$/ktCO2e"

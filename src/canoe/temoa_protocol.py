import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel
from temoa import TemoaConfig, TemoaMode, TemoaSequencer
from temoa.core.config import SolverNotAvailableError

SOLVER_DOC_LINKS = {
    "cbc": (
        "https://github.com/coin-or/Cbc#download "
        "(refer to temoa documentation for specific OS steps)"
    ),
    "gurobi": "https://www.gurobi.com/downloads/ (requires license and installation)",
    "cplex": (
        "https://www.ibm.com/products/ilog-cplex-optimization-studio "
        "(requires license and installation)"
    ),
    "highs": ("Did you mean to use appsi_highs? "),
    "glpk": "https://www.gnu.org/software/glpk/",
}


class CANOETemoaConfig(BaseModel):
    scenario: str = "canoe"
    scenario_mode: TemoaMode | str
    # input_database: Path
    # output_database: Path
    output_path: Path = Path("./temoa-outputs/")
    solver_name: str
    neos: bool = False
    save_excel: bool = False
    save_duals: bool = False
    save_storage_levels: bool = False
    save_lp_file: bool = False
    time_sequencing: str | None = None
    days_per_period: int = 365
    reserve_margin: str | None = None
    MGA: dict[str, object] | None = None
    SVMGA: dict[str, object] | None = None
    myopic: dict[str, object] | None = None
    morris: dict[str, object] | None = None
    monte_carlo: dict[str, object] | None = None
    stochastic_config: Path | None = None
    config_file: Path | None = None
    silent: bool = True
    stream_output: bool = False
    price_check: bool = True
    source_trace: bool = False
    check_units: bool = False
    plot_commodity_network: bool = False
    graphviz_output: bool = False
    cycle_count_limit: int = 100
    cycle_length_limit: int = 3
    output_threshold_capacity: float | None = None
    output_threshold_activity: float | None = None
    output_threshold_emission: float | None = None
    output_threshold_cost: float | None = None
    sqlite: dict[str, object] | None = None
    extensions: list[str] | tuple[str, ...] | None = None

    @classmethod
    def from_toml(cls, path: Path) -> "CANOETemoaConfig":
        with path.open("rb") as f:
            return CANOETemoaConfig.model_validate(tomllib.load(f))

    def to_temoa_config(
        self,
        db_path: Path,
    ) -> "TemoaConfig":
        self.output_path = self.output_path / Path(
            datetime.now().strftime("%Y%m%d%H%M%S")  # noqa: DTZ005
        )
        self.output_path.mkdir(parents=True, exist_ok=True)
        _check_temoa_solver(self.solver_name, self.save_duals)

        config_data: dict[str, Any] = {
            **self.model_dump(),
            "input_database": db_path,
            "output_database": db_path,
        }
        return TemoaConfig(**config_data)


def _check_temoa_solver(solver_name: str, save_duals: bool):
    is_available, location = TemoaConfig._check_solver_availability(solver_name)  # pyright: ignore[reportPrivateUsage]
    if not is_available:
        error_message = (
            f"The specified solver '{solver_name}' was not found.\n"
            "Please ensure the solver is installed and accessible.\n"
        )
        if solver_name.lower() in SOLVER_DOC_LINKS:
            link = SOLVER_DOC_LINKS[solver_name.lower()]
            error_message += f"For installation instructions, refer to: {link}\n"
        else:
            error_message += (
                "Refer to the solver's official documentation for "
                "installation instructions."
            )
        raise SolverNotAvailableError(error_message)
    else:
        logger.info("Using solver: %s (%s)", solver_name, location)

    if solver_name == "appsi_highs" and save_duals:
        raise ValueError(
            "save_duals is not supported with appsi_highs (it does not expose duals via the "
            + "APPSI interface). Disable save_duals or choose a different solver."
        )


def run_temoa(db_path: Path, config: CANOETemoaConfig):
    temoa_config = config.to_temoa_config(db_path)
    sequencer = TemoaSequencer(config=temoa_config)
    sequencer.start()

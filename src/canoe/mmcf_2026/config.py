"""
Configuration of the CANOE MMCF 2026 edits, the `[compiler.mmcf2026]` table of the pipeline
TOML (see `configuration/full-pipeline.toml`).

The edits change the database the sectors, the electricity module and the fuel
module have built, so they run after them. Each one is a sub-table that is applied
when present and left out otherwise.
"""

from pathlib import Path
from typing import ClassVar

from loguru import logger
from pydantic import ConfigDict

from canoe.common import CANOEProvince, CANOESector, atomic_transaction
from canoe.common.naming import DatasetIdentifier

from ..common.module_inheritance import InheritsFromBase, inherit
from . import (
    building_codes,
    candu_refurbishment,
    clean_electricity_regulation,
    coal_phaseout,
    unit_commitment,
)
from .building_codes import BuildingCodesConfig
from .candu_refurbishment import CANDURefurbishmentConfig
from .clean_electricity_regulation import CleanElectricityRegulationConfig
from .coal_phaseout import CoalPhaseoutConfig
from .unit_commitment import UnitCommitmentConfig


class CANOEMMCF2026Config(InheritsFromBase):
    """
    MMCF 2026 edits, `[compiler.mmcf2026]` in the pipeline TOML.

    Not an end-use sector: it runs once the other modules have run (see `run`). Fields
    marked as inherited take their value from `[compiler.base]`.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    _INHERIT_RESOLVERS: ClassVar = {
        "database_file": lambda base: Path(base.db_output_dir),
    }

    data_version: str = inherit()
    """Version in the data set codes (e.g. ELCHR003). Inherited."""

    database_file: Path = inherit()
    """Database edited. Inherited from `db_output_dir`."""

    future_periods: list[int] = inherit()
    """Model periods. Inherited."""

    period_step: int = inherit()
    """Length of a model period, in years. Inherited."""

    provinces: list[CANOEProvince] = inherit()
    """Regions of the model. Inherited."""

    building_codes: BuildingCodesConfig | None = None
    """Shell efficiency of the residential and commercial buildings."""

    coal_phaseout: CoalPhaseoutConfig | None = None
    """Phaseout of the existing coal generators."""

    candu_refurbishment: CANDURefurbishmentConfig | None = None
    """Refurbishment of the existing CANDU reactors."""

    clean_electricity_regulation: CleanElectricityRegulationConfig | None = None
    """Emission intensity cap on the fossil generators."""

    unit_commitment: UnitCommitmentConfig | None = None
    """Unit commitment of the thermal generators."""

    def run(self) -> None:
        # Written under the electricity data set
        data_id = DatasetIdentifier(
            sector=CANOESector.Electricity,
            code_description="HR",
            version=self.data_version,
        )
        with atomic_transaction(self.database_file) as conn:
            if self.building_codes is not None:
                logger.info("Applying building codes")
                building_codes.apply(conn, self.building_codes)
            if self.coal_phaseout is not None:
                logger.info("Applying coal phaseout")
                coal_phaseout.apply(
                    conn, self.coal_phaseout, self.future_periods, data_id
                )
            if self.candu_refurbishment is not None:
                logger.info("Applying CANDU refurbishment")
                candu_refurbishment.apply(
                    conn,
                    self.candu_refurbishment,
                    self.future_periods,
                    self.period_step,
                    data_id,
                )
            if self.clean_electricity_regulation is not None:
                logger.info("Applying the Clean Electricity Regulations")
                clean_electricity_regulation.apply(
                    conn,
                    self.clean_electricity_regulation,
                    self.future_periods,
                    data_id,
                )
            if self.unit_commitment is not None:
                logger.info("Adding unit commitment")
                unit_commitment.apply(conn, self.unit_commitment, self.provinces)

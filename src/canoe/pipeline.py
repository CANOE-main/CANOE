from pydantic import BaseModel

from .initializer import CANOEBaseConfig
from .initializer import run as run_initializer


class CANOEPipelineConfig(BaseModel):
    base: CANOEBaseConfig


def run(config: CANOEPipelineConfig):
    run_initializer(config.base)

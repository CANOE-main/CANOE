"""
Central emissions handling: emission commodities, costs and CO2-equivalents, shared by
all modules. See `processing` for the pipeline steps.
"""

from .config import EmissionsConfig

__all__ = [
    "EmissionsConfig",
]

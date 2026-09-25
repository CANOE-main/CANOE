from pathlib import Path

from pydantic import BaseModel, ConfigDict


class GoldConnectorConfig(BaseModel):
    """Local copy of the CANOE data lake (silver layer) the loaders read from."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    cache_dir: Path = Path(".cache")
    """Folder holding the cache, `<cache_dir>/silver/<cache_date>/...`."""

    cache_date: str
    """Date (YYYY-MM-DD) of the cached data lake snapshot to read."""

    force_sync: bool = False
    """Download the snapshot before running (not implemented yet)."""

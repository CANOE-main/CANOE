from pathlib import Path

from pydantic import BaseModel


class GoldConnectorConfig(BaseModel):
    cache_dir: Path = Path(".cache")
    cache_date: str
    force_sync: bool = False

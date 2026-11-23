"""
Install the local copy of the CANOE data lake (the cache) the loaders read from.

The cache is two archives on Google Drive, downloaded with gdown (the CANOE_CLOUD
gold connector's way, one file each to stay under Drive's rate limits):

- `silver.zip`: the silver layer, one folder per snapshot, `silver/<YYYY-MM-DD>/`;
- `renewables_cache.zip`: the wind and solar bins of the electricity module,
  `renewables/`.

The cache is immutable: installing only adds files that are not there yet, and never
overwrites one. A newer archive adds its new snapshot next to the old ones, so a
project pinned to a `cache_date` reads the same data forever. Each file is written
under a temporary name and renamed when complete, so an interrupted install leaves
no half-written file that later installs would keep.

Where the cache goes is the user's choice (`canoe cache install`, `canoe init`);
projects name it in `[compiler.base.data_cache_config]`.
"""

import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .config import GoldConnectorConfig


def cache_archives() -> dict[str, str]:
    """Google Drive file ID of each archive of the cache, by file name."""
    return {
        "silver.zip": "163zEbqGWosuEih9Al83-MuT_fW7VnZgU",
        "renewables_cache.zip": "1U8SxKezPpENb94-OGR-aFoUbq73q-M99",
    }


@dataclass(frozen=True)
class CacheContents:
    """What a cache folder holds."""

    snapshots: list[str]
    """Dates of the silver snapshots (`silver/<YYYY-MM-DD>/`), oldest first."""
    renewables: bool
    """Whether the wind and solar bins (`renewables/`) are there."""

    def is_empty(self) -> bool:
        return not self.snapshots and not self.renewables

    def has(self, cache_date: str) -> bool:
        """Whether a pipeline reading the snapshot of `cache_date` finds its data."""
        return cache_date in self.snapshots and self.renewables


def cache_contents(cache_dir: Path) -> CacheContents:
    """
    The snapshots and renewables in `cache_dir`.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     (Path(folder) / "silver" / "2026-08-10").mkdir(parents=True)
    ...     (Path(folder) / "silver" / "notes").mkdir()
    ...     cache_contents(Path(folder))
    CacheContents(snapshots=['2026-08-10'], renewables=False)
    """
    silver = cache_dir / "silver"
    snapshots = (
        sorted(
            d.name
            for d in silver.iterdir()
            if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name)
        )
        if silver.is_dir()
        else []
    )
    renewables = cache_dir / "renewables"
    has_renewables = renewables.is_dir() and any(renewables.glob("*.parquet"))
    return CacheContents(snapshots=snapshots, renewables=has_renewables)


def missing_from_cache(cache_config: GoldConnectorConfig) -> str | None:
    """
    What a pipeline reading `cache_config` would miss in its cache, with how to
    install it; None if the cache has the snapshot and the renewables.
    """
    contents = cache_contents(cache_config.cache_dir)
    if contents.has(cache_config.cache_date):
        return None
    missing: list[str] = []
    if cache_config.cache_date not in contents.snapshots:
        missing.append(f"the {cache_config.cache_date} snapshot")
    if not contents.renewables:
        missing.append("the renewables")
    return (
        f"The data cache at {cache_config.cache_dir} lacks {' and '.join(missing)}. "
        + f"Install it with: canoe cache install {cache_config.cache_dir}"
    )


@dataclass(frozen=True)
class ExtractedFiles:
    """Files of an archive: written, or already in the cache and left as they were."""

    added: int
    kept: int


def extract_new_files(archive: Path, cache_dir: Path) -> ExtractedFiles:
    """
    Extract the files of `archive` into `cache_dir` that are not there yet; the ones
    already there are kept as they are (the cache is immutable).
    """
    root = cache_dir.resolve()
    added = kept = 0
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            target = (root / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"{archive}: {member.filename} is outside the cache")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                kept += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.partial")
            with zip_file.open(member) as source, partial.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            os.replace(partial, target)
            added += 1
    return ExtractedFiles(added=added, kept=kept)


def install_cache(cache_dir: Path) -> CacheContents:
    """
    Download the archives of the cache and add their new files to `cache_dir`.

    Archives are downloaded to `<cache_dir>/.downloads/` (an interrupted download
    resumes there) and deleted once extracted. Returns what the cache holds after.
    """
    import gdown

    downloads = cache_dir / ".downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    for name, file_id in cache_archives().items():
        archive = downloads / name
        logger.info(f"Downloading {name} to {downloads}")
        gdown.download(id=file_id, output=str(archive), resume=True, use_cookies=False)
        logger.info(f"Extracting {name} into {cache_dir}")
        extracted = extract_new_files(archive, cache_dir)
        logger.info(
            f"{name}: {extracted.added} files added, {extracted.kept} already there"
        )
        archive.unlink()
    downloads.rmdir()
    return cache_contents(cache_dir)

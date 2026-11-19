import zipfile
from pathlib import Path
from typing import Any

import pytest

from canoe.common.cache_connector import install
from canoe.common.cache_connector.install import (
    CacheContents,
    cache_contents,
    extract_new_files,
    install_cache,
)


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zip_file:
        for name, data in files.items():
            zip_file.writestr(name, data)
    return path


class TestExtractNewFiles:
    def test_adds_the_files(self, tmp_path: Path):
        archive = _zip(
            tmp_path / "silver.zip", {"silver/2026-08-10/a/a_2026-08-10.parquet": b"a"}
        )
        cache = tmp_path / "cache"
        extracted = extract_new_files(archive, cache)
        assert (extracted.added, extracted.kept) == (1, 0)
        assert (cache / "silver/2026-08-10/a/a_2026-08-10.parquet").read_bytes() == b"a"

    def test_never_overwrites_a_file(self, tmp_path: Path):
        cache = tmp_path / "cache"
        existing = cache / "silver/2026-08-10/a.parquet"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"old")
        archive = _zip(
            tmp_path / "silver.zip",
            {
                "silver/2026-08-10/a.parquet": b"new",
                "silver/2026-09-01/a.parquet": b"newer snapshot",
            },
        )
        extracted = extract_new_files(archive, cache)
        assert (extracted.added, extracted.kept) == (1, 1)
        assert existing.read_bytes() == b"old"
        assert (cache / "silver/2026-09-01/a.parquet").read_bytes() == b"newer snapshot"

    def test_leaves_no_partial_files(self, tmp_path: Path):
        archive = _zip(tmp_path / "r.zip", {"renewables/cost_fixed.parquet": b"x"})
        cache = tmp_path / "cache"
        extract_new_files(archive, cache)
        assert [p.name for p in (cache / "renewables").iterdir()] == [
            "cost_fixed.parquet"
        ]

    def test_rejects_files_outside_the_cache(self, tmp_path: Path):
        archive = _zip(tmp_path / "bad.zip", {"../outside.txt": b"x"})
        with pytest.raises(ValueError, match="outside the cache"):
            extract_new_files(archive, tmp_path / "cache")
        assert not (tmp_path / "outside.txt").exists()


class TestCacheContents:
    def test_empty_folder(self, tmp_path: Path):
        contents = cache_contents(tmp_path / "missing")
        assert contents.is_empty()
        assert not contents.has("2026-08-10")

    def test_needs_the_snapshot_and_the_renewables(self, tmp_path: Path):
        (tmp_path / "silver/2026-08-10").mkdir(parents=True)
        assert not cache_contents(tmp_path).has("2026-08-10")
        (tmp_path / "renewables").mkdir()
        (tmp_path / "renewables/cost_fixed.parquet").write_bytes(b"x")
        contents = cache_contents(tmp_path)
        assert contents == CacheContents(snapshots=["2026-08-10"], renewables=True)
        assert contents.has("2026-08-10")
        assert not contents.has("2026-09-01")


def test_install_downloads_and_extracts_each_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archives = {
        "silver.zip": {"silver/2026-08-10/a.parquet": b"a"},
        "renewables_cache.zip": {"renewables/cost_fixed.parquet": b"r"},
    }
    ids = {file_id: name for name, file_id in install.cache_archives().items()}

    def fake_download(*, id: str, output: str, **_: Any) -> str:
        return str(_zip(Path(output), archives[ids[id]]))

    monkeypatch.setattr("gdown.download", fake_download)
    contents = install_cache(tmp_path / "cache")
    assert contents == CacheContents(snapshots=["2026-08-10"], renewables=True)
    # The archives are deleted once extracted
    assert not (tmp_path / "cache" / ".downloads").exists()

from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import tsam.timeseriesaggregation as tsam
from pydantic import ValidationError

from canoe.representative_periods.clusterings import TsamClustering, TsamCollection

COLLECTION = "weather2018-hierarchical-pca6"


# ---- TsamCollection ----------------------------------------------------------------


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    """The packaged collection's features, as tsam scaled them."""
    resource = files("canoe.representative_periods").joinpath(
        f"data/clusterings/{COLLECTION}/features.csv"
    )
    with resource.open("rb") as f:
        return pd.read_csv(
            f, index_col=["season", "hour"], float_precision="round_trip"
        )


def tsam_mapping(features: pd.DataFrame, collection: TsamCollection) -> dict[str, str]:
    """The mapping tsam computes itself, with the old module's arguments."""
    seasons = list(features.index.unique("season"))
    aggregation = tsam.TimeSeriesAggregation(
        features.reset_index(drop=True),
        noTypicalPeriods=collection.n_periods - len(collection.forced_days),
        hoursPerPeriod=24,
        clusterMethod="hierarchical",
        extremePeriodMethod="new_cluster_center",
        addManual=[seasons.index(day) for day in collection.forced_days],
        resolution=1,
    )
    aggregation.createTypicalPeriods()
    centres = aggregation.clusterCenterIndices
    assert centres is not None
    representatives = list(centres) + [
        p["stepNo"] for p in aggregation.extremePeriods.values()
    ]
    return {
        seasons[day]: seasons[representatives[cluster]]
        for day, cluster in enumerate(aggregation.clusterOrder)
    }


@pytest.mark.parametrize(
    "forced_days", [[], ["D041", "D201"], ["D006", "D101", "D301", "D218"]]
)
@pytest.mark.parametrize("n_periods", [10, 64])
def test_collection_same_mapping_as_tsam(
    features: pd.DataFrame, n_periods: int, forced_days: list[str]
):
    collection = TsamCollection(
        collection=COLLECTION, n_periods=n_periods, forced_days=forced_days
    )
    assert collection.mapping().representative_of == tsam_mapping(features, collection)


def test_collection_forced_representative_is_skipped():
    base = TsamCollection(collection=COLLECTION, n_periods=10).mapping()
    representative = next(iter(set(base.representative_of.values())))
    collection = TsamCollection(
        collection=COLLECTION, n_periods=11, forced_days=[representative]
    )
    assert collection.mapping() == base


def test_collection_unknown_forced_day():
    collection = TsamCollection(
        collection=COLLECTION, n_periods=10, forced_days=["D400"]
    )
    with pytest.raises(ValueError, match="D400"):
        collection.mapping()


def test_collection_no_cluster_left():
    with pytest.raises(ValidationError, match="no cluster"):
        TsamCollection(collection=COLLECTION, n_periods=2, forced_days=["D041", "D201"])


# ---- TsamClustering ----------------------------------------------------------------


def write_series(path: Path, name: str, times: pd.DatetimeIndex, values: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time": times.strftime("%Y-%m-%d %H:%M:%S%z"), name: values}).to_csv(
        path, index=False
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """
    Ten days of 2018 (UTC times) in two regimes: cold days D001-D005 and warm days
    D006-D010, with the coldest hour on D003 and the windiest day D008; plus a load
    series in another folder.
    """
    times = pd.date_range("2018-01-01 05:00", periods=240, freq="h", tz="UTC")
    hours = np.arange(240)
    day = hours // 24
    rng = np.random.default_rng(0)
    temperature = np.where(day < 5, -10.0, 15.0) + rng.normal(0, 0.5, 240)
    temperature[2 * 24 + 6] = -30.0
    wind = np.where(day == 7, 20.0, 5.0) + rng.normal(0, 0.1, 240)
    write_series(
        tmp_path / "on/on_temperature.csv", "on_temperature", times, temperature
    )
    write_series(tmp_path / "on/on_wind_speed.csv", "on_wind_speed", times, wind)
    write_series(tmp_path / "ontario/load.csv", "load", times, 100 + temperature)
    return tmp_path


def cold_and_warm(mapping: dict[str, str]) -> bool:
    cold = {f"D{d:03d}" for d in range(1, 6)}
    return all((day in cold) == (rep in cold) for day, rep in mapping.items())


def test_clustering_two_regimes(data_dir: Path):
    clustering = TsamClustering(
        data_dir=data_dir,
        weather_year=2018,
        include=["*_temperature"],
        pca_components=None,
        n_periods=2,
    )
    mapping = clustering.mapping().representative_of
    assert sorted(mapping) == [f"D{d:03d}" for d in range(1, 11)]
    assert len(set(mapping.values())) == 2
    assert cold_and_warm(mapping)


def test_clustering_extremes_of_any_series(data_dir: Path):
    clustering = TsamClustering(
        data_dir=data_dir,
        weather_year=2018,
        exclude=["ontario/*"],
        pca_components=1,
        n_periods=4,
        min_peak=["on_temperature"],
        max_mean=["load", "on_temperature"],
    )
    mapping = clustering.mapping().representative_of
    # D003 is the coldest, the warm day with the highest mean is also added
    assert mapping["D003"] == "D003"
    assert len(set(mapping.values())) == 4
    assert cold_and_warm(mapping)


def test_clustering_forced_and_extreme_day_counted_once(data_dir: Path):
    clustering = TsamClustering(
        data_dir=data_dir,
        weather_year=2018,
        include=["on/*"],
        n_periods=3,
        pca_components=2,
        forced_days=["D003"],
        min_peak=["on_temperature"],
    )
    mapping = clustering.mapping().representative_of
    assert mapping["D003"] == "D003"
    assert len(set(mapping.values())) == 3


def test_clustering_days_not_covered_are_left_out(data_dir: Path):
    times = pd.date_range("2018-01-01 05:00", periods=200, freq="h", tz="UTC")
    write_series(data_dir / "short.csv", "short", times, np.arange(200.0))
    clustering = TsamClustering(
        data_dir=data_dir, weather_year=2018, pca_components=2, n_periods=2
    )
    assert sorted(clustering.mapping().representative_of) == [
        f"D{d:03d}" for d in range(1, 9)
    ]


def test_clustering_include_and_exclude():
    with pytest.raises(ValidationError, match="not both"):
        TsamClustering(
            data_dir=Path("."),
            weather_year=2018,
            include=["a"],
            exclude=["b"],
            n_periods=2,
        )


def test_clustering_unmatched_pattern(data_dir: Path):
    clustering = TsamClustering(
        data_dir=data_dir, weather_year=2018, include=["*_humidity"], n_periods=2
    )
    with pytest.raises(ValueError, match="_humidity"):
        clustering.mapping()


def test_clustering_times_without_offset(data_dir: Path):
    pd.DataFrame({"time": ["2018-01-01 00:00"], "x": [1.0]}).to_csv(
        data_dir / "x.csv", index=False
    )
    clustering = TsamClustering(
        data_dir=data_dir, weather_year=2018, include=["x"], n_periods=1
    )
    with pytest.raises(ValueError, match="UTC offset"):
        clustering.mapping()

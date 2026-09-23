import numpy as np
import pandas as pd
import pytest

from canoe.canoe_objects.labeled_array import LabeledArray


def make_simple_array():
    return LabeledArray(
        coords={
            "period": ["2023", "2024"],
            "region": ["ON", "AB"],
            "time": [1, 2, 3],
        }
    )


def make_complex_array(fill: float = np.nan):
    return LabeledArray(
        coords={
            "period": [2023, 2024, 2025, 2030, 2035, 2040],
            "region": ["ON", "AB", "BC"],
            "season": ["D01", "D02", "D03"],
            "tod": [f"H{i:02d}" for i in range(1, 25)],
        },
        fill=fill,
    )


def test_set_and_get_single_cell():
    la = make_simple_array()
    la.set(99, period="2024", region="ON", time=2)
    assert la.get(period="2024", region="ON", time=2) == 99


def test_set_block_broadcasts_over_omitted_dim():
    la = make_simple_array()
    matrix = [[1, 2, 3], [4, 5, 6]]
    la.set_block(matrix, dims=("region", "time"))
    assert la.get(period="2023", region="ON", time=1) == 1
    assert la.get(period="2024", region="ON", time=1) == 1


def test_set_block_wrong_shape_raises():
    la = make_simple_array()
    with pytest.raises(ValueError):
        la.set_block([[1, 2], [3, 4]], dims=("region", "time"))


def test_repeat_series_single_element():
    la = make_complex_array()
    series = np.arange(1, 25)
    la.set_block(series, dims=("tod",))
    assert la.get(tod="H01", region="ON", season="D01", period=2023) == 1
    assert la.get(tod="H24", region="ON", season="D01", period=2040) == 24


def test_repeat_series_tensor():
    la = make_complex_array()
    series = np.arange(1, 25)
    la.set_block(series, dims=("tod",))
    assert (la.get(tod="H01", region="ON", period=2023) == np.array([1] * 3)).all()
    assert (la.get(tod="H24", season="D01", region="ON") == np.array([24] * 6)).all()


def test_incorrect_dim_raises():
    la = make_complex_array()
    with pytest.raises(ValueError):
        la.set_block([[1, 2], [3, 4]], dims=("region", "time"))


def test_fill():
    la = make_complex_array(fill=0.0)
    assert la.get(period=2023, region="ON", season="D01", tod="H01") == 0.0
    la = make_complex_array(fill=10.0)
    assert la.get(period=2023, region="ON", season="D01", tod="H01") == 10.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def coords():
    return {"region": ["A", "B"], "year": [2020, 2021]}


@pytest.fixture
def df_complete():
    return pd.DataFrame(
        {
            "region": ["A", "A", "B", "B"],
            "year": [2020, 2021, 2020, 2021],
            "value": [10, 20, 30, 40],
        }
    )


@pytest.fixture
def df_partial():
    # Missing (B, 2021)
    return pd.DataFrame(
        {
            "region": ["A", "A", "B"],
            "year": [2020, 2021, 2020],
            "value": [10, 20, 30],
        }
    )


@pytest.fixture
def df_duplicates():
    # Two rows for (A, 2020): should be aggregated
    return pd.DataFrame(
        {
            "region": ["A", "A", "A", "B"],
            "year": [2020, 2020, 2021, 2020],
            "value": [10, 5, 20, 30],
        }
    )


# ---------------------------------------------------------------------------
# from_df (classmethod / full constructor)
# ---------------------------------------------------------------------------


class TestFromDf:
    def test_shape_and_dims(self, df_complete):
        arr = LabeledArray.from_df(df_complete, dims=["region", "year"])
        assert arr.dims == ["region", "year"]
        assert arr.shape == (2, 2)

    def test_values_placed_correctly(self, df_complete):
        arr = LabeledArray.from_df(df_complete, dims=["region", "year"])
        assert arr.get(region="A", year=2020) == 10
        assert arr.get(region="A", year=2021) == 20
        assert arr.get(region="B", year=2020) == 30
        assert arr.get(region="B", year=2021) == 40

    def test_coords_sorted_and_derived_from_df(self, df_complete):
        arr = LabeledArray.from_df(df_complete, dims=["region", "year"])
        assert arr.coords["region"] == ["A", "B"]
        assert arr.coords["year"] == [2020, 2021]

    def test_fill_value_used_for_missing_combo(self, df_partial):
        arr = LabeledArray.from_df(df_partial, dims=["region", "year"], fill=-1)
        assert arr.get(region="B", year=2021) == -1

    def test_default_fill_is_nan(self, df_partial):
        arr = LabeledArray.from_df(df_partial, dims=["region", "year"])
        assert np.isnan(arr.get(region="B", year=2021))

    def test_dim_order_controls_axes(self, df_complete):
        arr = LabeledArray.from_df(df_complete, dims=["year", "region"])
        assert arr.dims == ["year", "region"]
        assert (
            arr.get(region="A", year=2020) == 10
        )  # get() is order-agnostic via kwargs

    def test_aggregation_sum_default(self, df_duplicates):
        arr = LabeledArray.from_df(df_duplicates, dims=["region", "year"])
        assert arr.get(region="A", year=2020) == 15  # 10 + 5

    def test_aggregation_mean(self, df_duplicates):
        arr = LabeledArray.from_df(df_duplicates, dims=["region", "year"], agg="mean")
        assert arr.get(region="A", year=2020) == 7.5  # (10 + 5) / 2

    def test_missing_dim_column_raises(self, df_complete):
        with pytest.raises(ValueError, match="missing columns"):
            LabeledArray.from_df(df_complete, dims=["region", "quarter"])

    def test_missing_value_col_raises(self, df_complete):
        with pytest.raises(ValueError, match="value column"):
            LabeledArray.from_df(
                df_complete, dims=["region", "year"], value_col="amount"
            )

    def test_custom_value_col(self, df_complete):
        df = df_complete.rename(columns={"value": "amount"})
        arr = LabeledArray.from_df(df, dims=["region", "year"], value_col="amount")
        assert arr.get(region="A", year=2020) == 10

    def test_single_dim(self):
        df = pd.DataFrame({"region": ["A", "B", "C"], "value": [1, 2, 3]})
        arr = LabeledArray.from_df(df, dims=["region"])
        assert arr.shape == (3,)
        assert arr.get(region="B") == 2

    def test_three_dims(self):
        df = pd.DataFrame(
            {
                "region": ["A", "A", "B"],
                "year": [2020, 2021, 2020],
                "category": ["x", "x", "y"],
                "value": [1, 2, 3],
            }
        )
        arr = LabeledArray.from_df(df, dims=["region", "year", "category"])
        assert arr.shape == (2, 2, 2)
        assert arr.get(region="A", year=2020, category="x") == 1
        assert np.isnan(arr.get(region="B", year=2021, category="y"))

    def test_fill_value_used_for_missing_combo(self, df_partial):
        arr = LabeledArray.from_df(df_partial, dims=["region", "year"], fill=-1)
        assert arr.get(region="B", year=2021) == -1

    def test_default_fill_is_nan(self, df_partial):
        arr = LabeledArray.from_df(df_partial, dims=["region", "year"])
        assert np.isnan(arr.get(region="B", year=2021))


# ---------------------------------------------------------------------------
# fill_from_df (instance method)
# ---------------------------------------------------------------------------


class TestFillFromDf:
    def test_fills_existing_array(self, coords, df_complete):
        arr = LabeledArray(coords, fill=0)
        arr.fill_from_df(df_complete)
        assert arr.get(region="A", year=2020) == 10
        assert arr.get(region="A", year=2021) == 20
        assert arr.get(region="B", year=2020) == 30
        assert arr.get(region="B", year=2021) == 40

    def test_missing_combo_becomes_nan(self, coords, df_partial):
        arr = LabeledArray(coords, fill=-1)
        arr.fill_from_df(df_partial)
        assert arr.get(region="B", year=2020) == 30
        assert np.isnan(arr.get(region="B", year=2021))  # overwritten, not kept at fill

    def test_second_call_overwrites_first_call_entirely(self, coords):
        arr = LabeledArray(coords, fill=np.nan)
        df1 = pd.DataFrame({"region": ["A"], "year": [2020], "value": [10]})
        df2 = pd.DataFrame({"region": ["B"], "year": [2021], "value": [40]})

        arr.fill_from_df(df1)
        arr.fill_from_df(df2)

        # df2 did not mention (A, 2020); plain overwrite means it is gone, not kept
        assert np.isnan(arr.get(region="A", year=2020))
        assert arr.get(region="B", year=2021) == 40
        assert np.isnan(arr.get(region="A", year=2021))
        assert np.isnan(arr.get(region="B", year=2020))

    def test_second_call_updates_repeated_cell(self, coords):
        arr = LabeledArray(coords, fill=np.nan)
        df1 = pd.DataFrame({"region": ["A"], "year": [2020], "value": [10]})
        df2 = pd.DataFrame({"region": ["A"], "year": [2020], "value": [99]})

        arr.fill_from_df(df1)
        arr.fill_from_df(df2)

        assert arr.get(region="A", year=2020) == 99

    def test_aggregation_sum_default(self, coords, df_duplicates):
        arr = LabeledArray(coords, fill=0)
        arr.fill_from_df(df_duplicates)
        assert arr.get(region="A", year=2020) == 15  # 10 + 5

    def test_aggregation_mean(self, coords, df_duplicates):
        arr = LabeledArray(coords, fill=0)
        arr.fill_from_df(df_duplicates, agg="mean")
        assert arr.get(region="A", year=2020) == 7.5  # (10 + 5) / 2

    def test_custom_value_col(self, coords, df_complete):
        arr = LabeledArray(coords, fill=0)
        df = df_complete.rename(columns={"value": "amount"})
        arr.fill_from_df(df, value_col="amount")
        assert arr.get(region="A", year=2020) == 10

    def test_missing_dim_column_raises(self, coords, df_complete):
        arr = LabeledArray(coords)
        df = df_complete.drop(columns=["year"])
        with pytest.raises(ValueError, match="missing columns"):
            arr.fill_from_df(df)

    def test_missing_value_col_raises(self, coords, df_complete):
        arr = LabeledArray(coords)
        with pytest.raises(ValueError, match="value column"):
            arr.fill_from_df(df_complete, value_col="amount")

    def test_unknown_coordinate_value_dropped_silently(self, coords):
        arr = LabeledArray(coords, fill=0)
        df = pd.DataFrame(
            {
                "region": ["A", "C"],  # "C" not in coords
                "year": [2020, 2020],
                "value": [10, 999],
            }
        )
        arr.fill_from_df(df)
        assert arr.get(region="A", year=2020) == 10
        assert "C" not in arr.coords["region"]

    def test_dims_order_does_not_affect_placement(self, coords, df_complete):
        arr = LabeledArray(coords, fill=0)
        arr.fill_from_df(df_complete, dims=["year", "region"])
        assert arr.get(region="A", year=2020) == 10
        assert arr.get(region="B", year=2021) == 40

    def test_subset_dims_broadcasts_over_omitted_dim(self):
        arr = LabeledArray({"region": ["A", "B"], "year": [2020, 2021]}, fill=0)
        df = pd.DataFrame({"region": ["A", "B"], "value": [7, 8]})
        arr.fill_from_df(df, dims=["region"])
        assert arr.get(region="A", year=2020) == 7
        assert arr.get(region="A", year=2021) == 7
        assert arr.get(region="B", year=2020) == 8
        assert arr.get(region="B", year=2021) == 8

    def test_subset_dims_partial_df_sets_nan_for_omitted_combo(self):
        arr = LabeledArray({"region": ["A", "B"], "year": [2020, 2021]}, fill=-1)
        df = pd.DataFrame({"region": ["A"], "value": [7]})
        arr.fill_from_df(df, dims=["region"])
        assert arr.get(region="A", year=2020) == 7
        assert arr.get(region="A", year=2021) == 7
        assert np.isnan(arr.get(region="B", year=2020))
        assert np.isnan(arr.get(region="B", year=2021))

    def test_missing_combo_uses_given_fill(self, coords, df_partial):
        arr = LabeledArray(coords, fill=0)  # array's own fill, irrelevant here
        arr.fill_from_df(df_partial, fill=-1)
        assert arr.get(region="B", year=2020) == 30
        assert arr.get(region="B", year=2021) == -1

    def test_missing_combo_defaults_to_nan(self, coords, df_partial):
        arr = LabeledArray(coords, fill=0)
        arr.fill_from_df(df_partial)  # no fill given, defaults NaN
        assert np.isnan(arr.get(region="B", year=2021))

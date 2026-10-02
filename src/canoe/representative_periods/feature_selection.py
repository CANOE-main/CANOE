import pandas as pd

from canoe.representative_periods import utils


# Returns the period index (may be multi-day) with the highest mean value of a given timeseries
def max_mean_period(feature_config: dict):

    df_timeseries = pd.read_csv(
        f"timeseries/{feature_config['timeseries']}.csv", index_col=0
    )

    n_days = feature_config["days_in_period"]
    total_periods = len(df_timeseries) // (
        24 * n_days
    )  # number of n-day periods in the timeseries

    if n_days % utils.config["days_per_period"] != 0:
        print(
            "Tried to add a max_mean_period feature but length of typical periods did not fit "
            "neatly inside length of feature period. Would cause indexing issues. Feature skipped."
        )
        return []
    else:
        typ_per_feature = (
            n_days // utils.config["days_per_period"]
        )  # how many typical periods fit inside this feature period?

    # Get the n_day period with highest mean value
    max_mean = 0
    max_index = 0
    for p in range(total_periods):
        mean = period_mean(p, df_timeseries, n_days)

        # New high score
        if mean > max_mean:
            max_index = p
            max_mean = mean

    # Convert to indices in the context of typical periods -> may be different length periods
    indices = list(
        range(
            typ_per_feature * max_index, typ_per_feature * max_index + typ_per_feature
        )
    )
    return indices


# Get the mean value of a timeseries
def period_mean(p, df_timeseries, days_per_period):

    start_index = 24 * days_per_period * p
    end_index = start_index + 24 * days_per_period - 1

    # This period goes beyond the end of the timeseries so quit
    if end_index >= len(df_timeseries):
        print(p, end_index, len(df_timeseries))
        return

    # Otherwise return the mean
    return df_timeseries.iloc[start_index:end_index].mean().iloc[0]

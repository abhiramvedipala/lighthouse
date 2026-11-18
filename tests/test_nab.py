import pandas as pd

from lighthouse.nab import to_dataset


def test_five_minute_points_become_minute_rows_and_windows_become_incidents():
    idx = pd.date_range("2014-01-01", periods=2000, freq="5min")
    idx = idx.insert(5, idx[5])  # NAB files contain a few repeated stamps
    s = pd.Series(range(len(idx)), index=idx, dtype=float)
    ds = to_dataset(s, [["2014-01-02 00:00:00", "2014-01-02 06:00:00"]])
    assert ds.minutes == 2000 * 5 and len(ds.agg) == ds.minutes
    assert ds.incidents[0].end - ds.incidents[0].start == 360
    assert ds.splits["train"] == (0, int(ds.minutes * 0.35))

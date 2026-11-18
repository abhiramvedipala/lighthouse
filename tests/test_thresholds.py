import numpy as np
import pandas as pd

from lighthouse.evaluate import Incident
from lighthouse.thresholds import flags_from_scores, save_thresholds, select_threshold

WIN = (0, 2880)


def scores_with(peaks: dict[int, float], noise_peaks: dict[int, float] | None = None, n=2880, seed=0):
    rng = np.random.default_rng(seed)
    s = rng.uniform(0, 1, n)
    for m, v in {**peaks, **(noise_peaks or {})}.items():
        s[m] = v
    return pd.DataFrame({"a": s})


def inc(i, start):
    return Incident(f"i{i}", "latency_spike", frozenset({"a"}), start, start + 10)


def test_picks_a_threshold_that_separates_peaks_from_noise():
    sc = scores_with({100: 9.0, 500: 9.0, 900: 9.0})
    incs = [inc(1, 98), inc(2, 498), inc(3, 898)]
    r = select_threshold(sc, incs, WIN)
    assert r["feasible"] and r["recall"] == 1.0 and r["precision"] == 1.0
    assert 1.0 < r["threshold"] <= 9.0


def test_false_alarm_cap_forces_a_higher_threshold():
    # three real peaks of 5 and four false-alarm bumps of 7: catching all needs a threshold below 5,
    # which would allow 4 false alarms in 2 days = 2/day > 1/day, so the cap pushes the choice up.
    sc = scores_with({100: 5, 500: 5, 900: 5}, {1200: 7, 1500: 7, 1800: 7, 2200: 7})
    incs = [inc(1, 98), inc(2, 498), inc(3, 898)]
    capped = select_threshold(sc, incs, WIN, max_fa=1.0)
    loose = select_threshold(sc, incs, WIN, max_fa=10.0)
    assert capped["fa_per_service_day"] <= 1.0
    assert loose["recall"] == 1.0 and loose["fa_per_service_day"] > capped["fa_per_service_day"]
    assert capped["threshold"] >= loose["threshold"]


def test_infeasible_detector_is_reported_not_hidden():
    n = 2880
    sc = pd.DataFrame({"a": np.where(np.arange(n) % 5 == 0, 10.0, 0.0)})  # alarms constantly
    r = select_threshold(sc, [], WIN, max_fa=0.5)
    assert r["feasible"] is False or r["fa_per_service_day"] <= 0.5


def test_no_scores_gives_infinite_threshold():
    r = select_threshold(pd.DataFrame({"a": np.full(10, np.nan)}), [], (0, 10))
    assert r["threshold"] == float("inf") and r["feasible"] is False


def test_flags_from_scores_is_strictly_greater_than():
    f = flags_from_scores(pd.DataFrame({"a": [1.0, 2.0, 3.0]}), 2.0)
    assert f["a"].tolist() == [False, False, True]


def test_save_thresholds_round_trip(tmp_path):
    import json

    save_thresholds({"x": {"threshold": 1.5}}, tmp_path / "t.json")
    assert json.loads((tmp_path / "t.json").read_text()) == {"x": {"threshold": 1.5}}

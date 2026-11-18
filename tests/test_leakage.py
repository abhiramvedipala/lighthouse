"""Leakage tests: fitting never touches validation/test rows, thresholds never see test labels.

The poison test replaces every row after the train window with garbage and checks that nothing
computed on or before the train window changes. If a detector peeked at later rows (to fit, to
normalise, or through a non-causal rolling window) the scores would move.
"""
import numpy as np
import pytest

from lighthouse.data import Dataset, load_dataset
from lighthouse.detectors.seasonal import SeasonalBaseline
from lighthouse.detectors.static import StaticThreshold
from lighthouse.detectors.zscore import RollingZScore
from lighthouse.evaluate import Incident
from lighthouse.thresholds import select_threshold

DETECTORS = {
    "static_threshold": StaticThreshold,
    "rolling_zscore": RollingZScore,
    "seasonal_baseline": SeasonalBaseline,
}


def register(name, factory):
    DETECTORS[name] = factory


@pytest.fixture(scope="module")
def ds():
    return load_dataset("fixture")


def poison_after(ds: Dataset, minute: int, seed=0) -> Dataset:
    """Copy of ds whose numeric columns are random garbage from `minute` on."""
    rng = np.random.default_rng(seed)
    agg = ds.agg.copy()
    cut = ds.start + np.timedelta64(minute, "m")
    late = agg["ts"] >= cut
    for col in ("request_count", "error_count", "warn_error_lines", "distinct_error_sigs", "new_sigs_24h"):
        agg[col] = agg[col].astype("float64")
        agg.loc[late, col] = rng.integers(0, 500, late.sum())
    for col in ("error_rate", "p50_ms", "p95_ms", "p99_ms"):
        agg[col] = agg[col].astype("float64")
        agg.loc[late, col] = rng.uniform(0, 5000, late.sum())
    return Dataset(agg, ds.start, ds.minutes, ds.labels, ds.slo)


def test_splits_are_contiguous_ordered_and_disjoint(ds):
    s = ds.splits
    assert s["train"][0] == 0 and s["train"][1] == s["val"][0] and s["val"][1] == s["test"][0]
    assert s["test"][1] == ds.minutes
    assert s["train"][1] - s["train"][0] > s["val"][1] - s["val"][0]


@pytest.mark.parametrize("name", sorted(DETECTORS))
def test_fit_and_scores_before_the_train_cut_ignore_later_rows(ds, name):
    cut = ds.splits["train"][1]
    clean = DETECTORS[name]().fit(ds, ds.splits["train"]).score(ds)
    dirty_ds = poison_after(ds, cut)
    dirty = DETECTORS[name]().fit(dirty_ds, dirty_ds.splits["train"]).score(dirty_ds)
    np.testing.assert_allclose(clean.iloc[:cut].to_numpy(), dirty.iloc[:cut].to_numpy(), rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize("name", sorted(DETECTORS))
def test_scores_are_causal_at_a_validation_cut(ds, name):
    cut = ds.splits["val"][0] + 500
    clean = DETECTORS[name]().fit(ds, ds.splits["train"]).score(ds)
    dirty_ds = poison_after(ds, cut)
    dirty = DETECTORS[name]().fit(dirty_ds, ds.splits["train"]).score(dirty_ds)
    np.testing.assert_allclose(clean.iloc[:cut].to_numpy(), dirty.iloc[:cut].to_numpy(), rtol=1e-6, atol=1e-6)


def test_threshold_selection_ignores_everything_outside_the_validation_window(ds):
    scores = RollingZScore().fit(ds, ds.splits["train"]).score(ds)
    val = ds.splits["val"]
    incs = ds.incidents
    base = select_threshold(scores, incs, val)
    # scramble scores and labels of the test window: the choice must not move
    scrambled = scores.copy()
    scrambled.iloc[ds.splits["test"][0]:] = 1e9
    other = [Incident(i.id, i.type, i.services, i.start, i.end, i.benign)
             for i in incs if not (ds.splits["test"][0] <= i.start)]
    assert select_threshold(scrambled, other, val) == base


def test_fit_is_only_ever_given_the_train_window(ds):
    seen = {}

    class Spy(RollingZScore):
        def fit(self, d, window):
            seen["window"] = window
            return super().fit(d, window)

    Spy().fit(ds, ds.splits["train"])
    assert seen["window"] == ds.splits["train"]
    assert ds.train_mask(ds.services[0])[ds.splits["train"][1]:].sum() == 0  # masks never reach val or test

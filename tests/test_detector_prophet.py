import numpy as np
import pytest

from lighthouse.detectors.prophet_residual import ProphetResidual
from tests.test_detector_seasonal import sine_ds

TRAIN = (0, 3 * 1440)
SPIKE = slice(3 * 1440 + 600, 3 * 1440 + 660)


def make(**kw):
    return ProphetResidual(uncertainty_samples=50, **kw)


@pytest.fixture(scope="module")
def fitted():
    ds = sine_ds(spike=SPIKE)
    det = make().fit(ds, TRAIN)
    return ds, det, det.score(ds)["svc"].to_numpy()


def test_planted_spike_scores_far_above_normal_minutes(fitted):
    _, _, s = fitted
    held_out = np.delete(s[3 * 1440:], np.arange(600, 700))
    assert s[SPIKE].max() > 2.0 * np.percentile(held_out, 99.5)


def test_one_model_per_endpoint_and_signal_with_fit_time_logged(fitted):
    ds, det, _ = fitted
    assert len(det.models) == 3 * len(ds.keys)
    assert all(v > 0 for v in det.fit_seconds.values())


def test_normaliser_comes_from_the_train_window_only(fitted):
    ds, det, _ = fitted
    # re-score a dataset whose post-train rows are garbage: the normalisers are already fixed and equal
    garbage = sine_ds(spike=slice(3 * 1440 + 10, 3 * 1440 + 1400))
    before = dict(det.norm)
    det.score(garbage)
    assert det.norm == before


def test_scores_before_a_cut_ignore_later_data(fitted):
    ds, det, full = fitted
    cut = 4 * 1440
    both = np.concatenate([np.arange(SPIKE.start, SPIKE.stop), np.arange(cut + 5, cut + 300)])
    changed = sine_ds(spike=both)  # same planted spike as `full`, plus a new one after the cut
    part = det.score(changed)["svc"].to_numpy()
    np.testing.assert_allclose(full[:cut], part[:cut], rtol=1e-6, atol=1e-6)


def test_fit_ignores_post_train_rows_and_is_deterministic(fitted):
    _, _, s_full = fitted
    a = make().fit(sine_ds(), TRAIN)
    b = make().fit(sine_ds(spike=slice(3 * 1440 + 100, 3 * 1440 + 900)), TRAIN)
    ds = sine_ds()
    sa, sb = (d.score(ds)["svc"].to_numpy() for d in (a, b))
    np.testing.assert_allclose(sa[:3 * 1440], sb[:3 * 1440], rtol=1e-6, atol=1e-6)  # post-train rows changed
    # same seed, same train rows: the fixture model (spike after the train cut) scores the same before it
    np.testing.assert_allclose(sa[:SPIKE.start], s_full[:SPIKE.start], rtol=1e-6, atol=1e-6)


def test_scores_hold_inside_a_five_minute_bin_and_are_nonnegative(fitted):
    _, _, s = fitted
    assert (s >= 0).all()
    base = 3 * 1440 + 9  # a bin ends on this minute; the next four minutes inherit its score
    assert np.all(s[base:base + 5] == s[base])

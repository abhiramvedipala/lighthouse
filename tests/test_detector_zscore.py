import numpy as np

from lighthouse.detectors.zscore import RollingZScore
from tests.helpers import make_ds


def noisy(minutes=1500, seed=1):
    rng = np.random.default_rng(seed)
    count = rng.poisson(100, minutes)
    errs = rng.binomial(count, 0.003)
    p95 = 40 + rng.normal(0, 1.0, minutes)
    return count, errs, p95


def run(count, errs, p95):
    ds = make_ds(minutes=len(count), count=count, errs=errs, p95=p95)
    det = RollingZScore().fit(ds, (0, 800))
    return det.score(ds)["svc"].to_numpy()


def test_stable_series_has_low_scores():
    s = run(*noisy())
    assert np.percentile(s[800:], 99) < 6


def test_latency_spike_gets_a_high_score():
    count, errs, p95 = noisy()
    base = run(count, errs, p95)
    p95 = p95.copy()
    p95[1000:1015] *= 5
    spiked = run(count, errs, p95)
    assert spiked[1000:1015].max() > 5 * base[800:].max()


def test_error_burst_gets_a_high_score():
    count, errs, p95 = noisy()
    errs = errs.copy()
    errs[1000:1010] = (count[1000:1010] * 0.3).astype(int)
    assert run(count, errs, p95)[1000:1010].max() > 20


def test_slow_drift_is_largely_absorbed_by_the_ewma():
    count, errs, p95 = noisy()
    drift = p95.copy()
    drift[700:1500] *= np.linspace(1, 2.5, 800)  # climbs 2.5x over 13 hours
    spike = p95.copy()
    spike[1000:1015] *= 2.5
    assert run(count, errs, drift)[800:].max() < run(count, errs, spike)[1000:1015].max() / 3


def test_scores_use_the_past_only():
    count, errs, p95 = noisy()
    full = run(count, errs, p95)
    p2 = p95.copy()
    p2[1200:] = 500  # change the future
    changed = run(count, errs, p2)
    np.testing.assert_allclose(full[:1200], changed[:1200])


def test_std_floor_prevents_infinite_z_on_zero_variance_error_rate():
    count = np.full(1500, 100)
    errs = np.zeros(1500, dtype=int)
    errs[1000] = 1
    s = run(count, errs, np.full(1500, 40.0))
    assert np.isfinite(s).all() and s.max() < 1e6

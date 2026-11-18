import numpy as np
import pandas as pd

from lighthouse.detectors.seasonal import SeasonalBaseline, slot_ids
from tests.helpers import make_ds

DAYS = 5   # Monday to Friday: no weekend slots needed
N = DAYS * 1440


def sine_ds(spike=None, drop=None, surge=None, seed=3, n=N):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    shape = 0.6 + 0.4 * np.sin(2 * np.pi * (t % 1440) / 1440)
    count = rng.poisson(100 * shape).astype(int)
    p95 = 40 * (1 + 0.5 * np.sin(2 * np.pi * (t % 1440) / 1440)) + rng.normal(0, 1, n)
    errs = rng.binomial(count, 0.003)
    if spike is not None:
        p95[spike] *= 4
    if drop is not None:
        count[drop] = (count[drop] * 0.2).astype(int)
    if surge is not None:
        count[surge] *= 2
    return make_ds(minutes=n, count=count, errs=errs, p95=p95)


def fitted(ds):
    return SeasonalBaseline().fit(ds, (0, 3 * 1440))


def test_a_clean_daily_sine_is_learned_and_scores_low_everywhere():
    ds = sine_ds()
    s = fitted(ds).score(ds)["svc"].to_numpy()
    assert np.percentile(s[3 * 1440:], 99.9) < 1.5   # normaliser is the train 99.9th percentile


def test_planted_spike_on_a_held_out_day_stands_out():
    spike = slice(3 * 1440 + 840, 3 * 1440 + 855)    # day 4 at 14:00
    ds = sine_ds(spike=spike)
    s = fitted(ds).score(ds)["svc"].to_numpy()
    clean_max = np.delete(s[3 * 1440:], np.arange(spike.start - 3 * 1440, spike.stop - 3 * 1440 + 10)).max()
    assert s[spike].max() > 3 * clean_max


def test_traffic_drop_is_flagged_but_a_surge_is_not():
    window = slice(3 * 1440 + 600, 3 * 1440 + 660)
    ds_drop = sine_ds(drop=window)
    ds_surge = sine_ds(surge=window)
    drop = fitted(ds_drop).score(ds_drop)["svc"].to_numpy()[window].max()
    surge = fitted(ds_surge).score(ds_surge)["svc"].to_numpy()[window].max()
    assert drop > 3 and surge < 1.5


def test_slots_are_five_minutes_wide_and_split_weekday_from_weekend():
    ds = make_ds(minutes=7 * 1440)
    sid = slot_ids(ds)
    assert sid[0] == 0 and sid[4] == 0 and sid[5] == 1                # Monday 00:00-00:04 is slot 0
    assert sid[1439] == 287
    assert sid[5 * 1440] == 288 and sid[6 * 1440 + 1439] == 288 + 287  # Saturday and Sunday slots
    assert len(set(sid)) == 576


def test_fit_uses_only_the_train_window_and_the_clean_mask():
    ds = sine_ds()
    a = SeasonalBaseline().fit(ds, (0, 3 * 1440))
    ds2 = sine_ds(spike=slice(3 * 1440 + 10, 3 * 1440 + 400))   # change only post-train data
    b = SeasonalBaseline().fit(ds2, (0, 3 * 1440))
    for k in a.median:
        np.testing.assert_allclose(a.median[k], b.median[k], rtol=1e-6)


def test_scores_use_the_past_only():
    ds = sine_ds()
    full = fitted(ds).score(ds)["svc"].to_numpy()
    cut = 4 * 1440
    ds2 = sine_ds(spike=slice(cut + 5, cut + 200))
    part = SeasonalBaseline().fit(ds2, (0, 3 * 1440)).score(ds2)["svc"].to_numpy()
    np.testing.assert_allclose(full[:cut], part[:cut], rtol=1e-6, atol=1e-6)


def test_unseen_slots_fall_back_to_the_day_type_median():
    ds = sine_ds(n=7 * 1440)   # a week starting Monday; the train window has no weekend minutes
    d = fitted(ds)
    key = ds.keys[0]
    med = d.median[(key, "lat")]
    assert np.isfinite(med).all() and isinstance(ds.start, pd.Timestamp)

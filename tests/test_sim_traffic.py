import numpy as np
import pandas as pd
import pytest

from lighthouse.sim.config import load_sim_config
from lighthouse.sim.traffic import build_params, minute_index, sample_requests, seasonal_shape


@pytest.fixture(scope="module")
def cfg():
    return load_sim_config(days=2, rate_scale=0.5)


def run(cfg, seed_offset=0):
    r_traffic, _, r_logs = cfg.child_rngs()
    p = build_params(cfg, r_traffic)
    return p, sample_requests(p, r_logs)


def test_daily_peak_is_at_peak_hour(cfg):
    idx = pd.date_range("2026-10-05", periods=1440, freq="min")
    shape = seasonal_shape(idx, cfg)
    assert idx[shape.argmax()].hour == 14
    assert shape.min() == pytest.approx(0.2, abs=0.01)


def test_weekend_is_sixty_percent_of_weekday(cfg):
    idx = pd.date_range("2026-10-05", periods=7 * 1440, freq="min")
    shape = pd.Series(seasonal_shape(idx, cfg), index=idx)
    weekday = shape[shape.index.day_of_week == 1].sum()
    weekend = shape[shape.index.day_of_week == 5].sum()
    assert weekend / weekday == pytest.approx(0.6, rel=1e-6)


def test_same_seed_same_output(cfg):
    _, a = run(cfg)
    _, b = run(cfg)
    pd.testing.assert_frame_equal(a, b)


def test_different_seed_differs():
    a = run(load_sim_config(days=1, seed=1, rate_scale=0.5))[1]
    b = run(load_sim_config(days=1, seed=2, rate_scale=0.5))[1]
    assert len(a) != len(b) or not a["ts"].equals(b["ts"])


def test_request_volume_within_bounds():
    cfg = load_sim_config(days=1)
    _, req = run(cfg)
    # one weekday at full scale: roughly 290 req/min peak * mean shape 0.6 * 1440
    assert 150_000 < len(req) < 500_000


def test_error_rate_near_base(cfg):
    _, req = run(cfg)
    rate = (req["status"] >= 500).mean()
    assert rate == pytest.approx(cfg.base_error_rate, rel=0.2)


def test_latency_median_matches_config(cfg):
    _, req = run(cfg)
    for i, e in enumerate(cfg.endpoints):
        med = np.median(req.loc[req["ep"] == i, "latency_ms"])
        assert med == pytest.approx(e.p50_ms, rel=0.1)


def test_timestamps_sorted_and_inside_window(cfg):
    _, req = run(cfg)
    assert req["ts"].is_monotonic_increasing
    start = cfg.start.value // 1_000_000
    assert req["ts"].min() >= start
    assert req["ts"].max() < start + cfg.minutes * 60_000


def test_minute_index_length(cfg):
    assert len(minute_index(cfg)) == 2 * 1440

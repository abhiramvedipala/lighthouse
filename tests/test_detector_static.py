import numpy as np

from lighthouse.detectors.static import StaticThreshold
from tests.helpers import make_ds


def flagged(ds):
    return StaticThreshold().score(ds)["svc"].to_numpy() >= 1.0


def test_quiet_series_never_fires():
    assert not flagged(make_ds()).any()


def test_p95_over_twice_slo_fires_on_the_fifth_minute_not_before():
    p95 = np.full(600, 40.0)
    p95[100:110] = 250  # SLO 100 -> limit 200
    f = flagged(make_ds(p95=p95))
    assert not f[:104].any() and f[104]            # fires when the 5th consecutive minute is reached
    assert f[104:110].all() and not f[110]         # and clears as soon as a minute is back under


def test_four_bad_minutes_do_not_fire():
    p95 = np.full(600, 40.0)
    p95[100:104] = 500
    assert not flagged(make_ds(p95=p95)).any()


def test_a_single_good_minute_resets_the_sustain_counter():
    p95 = np.full(600, 500.0)
    p95[103] = 40
    f = flagged(make_ds(p95=p95))
    assert f[4] and not f[103:107].any()            # the dip clears the alert and the count restarts
    assert f[108]                                   # 5th bad minute after the dip


def test_error_rate_over_five_percent_fires_and_exactly_five_percent_does_not():
    errs = np.zeros(600, dtype=int)
    errs[200:210] = 6      # 6% of 100
    f = flagged(make_ds(errs=errs))
    assert f[204] and not f[199]
    errs2 = np.zeros(600, dtype=int)
    errs2[200:210] = 5     # exactly 5%: ratio 1.0, the boundary counts as firing (>= 1.0)
    assert flagged(make_ds(errs=errs2))[204]


def test_minutes_without_requests_do_not_carry_latency_evidence():
    count = np.full(600, 100)
    count[100:110] = 0
    p95 = np.full(600, 500.0)
    f = flagged(make_ds(count=count, p95=p95))
    assert not f[104:110].any()


def test_slow_drift_below_two_times_slo_is_missed():
    p95 = np.linspace(40, 190, 600)  # climbs 4.7x but stays under the 200 ms limit
    assert not flagged(make_ds(p95=p95)).any()


def test_service_score_is_max_over_endpoints():
    ds = make_ds(services=(("svc", "GET /a"), ("svc", "GET /b")))
    s = StaticThreshold().score(ds)
    assert list(s.columns) == ["svc"] and len(s) == 600

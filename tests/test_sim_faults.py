import collections

import numpy as np
import pandas as pd
import pytest

from lighthouse.sim.config import load_sim_config
from lighthouse.sim.faults import BENIGN_COUNTS, FAULT_COUNTS
from lighthouse.sim.run import simulate


@pytest.fixture(scope="module")
def sim():
    cfg = load_sim_config()
    params, req, logs, labels = simulate(cfg)
    return cfg, params, req, logs, labels


def window(cfg, ev, pad=0):
    s = (pd.Timestamp(ev["start"]) - cfg.start) // pd.Timedelta("1min")
    e = (pd.Timestamp(ev["end"]) - cfg.start) // pd.Timedelta("1min")
    return int(s) - pad, int(e) + pad


def minute_stats(cfg, req, ep):
    r = req[req["ep"] == ep]
    t = ((r["ts"] - cfg.start.value // 1_000_000) // 60_000).astype(int)
    g = r.groupby(t)
    return pd.DataFrame({
        "n": g.size(),
        "err": g["status"].apply(lambda s: (s >= 500).mean()),
        "p95": g["latency_ms"].quantile(0.95),
    }).reindex(range(cfg.minutes))


def first(labels, typ):
    return next(f for f in labels["faults"] if f["type"] == typ)


def test_counts_match_spec(sim):
    _, _, _, _, labels = sim
    assert collections.Counter(f["type"] for f in labels["faults"]) == FAULT_COUNTS
    assert collections.Counter(b["type"] for b in labels["benign"]) == BENIGN_COUNTS
    assert 38 <= len(labels["faults"]) <= 42


def test_every_split_sees_faults_of_many_types(sim):
    cfg, _, _, _, labels = sim
    day = lambda f: (pd.Timestamp(f["start"]) - cfg.start).days + 1  # noqa: E731
    for lo, hi in ((1, 7), (8, 10), (11, 14)):
        types = {f["type"] for f in labels["faults"] if lo <= day(f) <= hi}
        assert len(types) >= 4, (lo, hi, types)
    assert sum(11 <= day(f) <= 14 for f in labels["faults"]) >= 8


def test_no_overlap_on_same_service(sim):
    _, _, _, _, labels = sim
    allev = labels["faults"] + labels["benign"]
    for a in allev:
        for b in allev:
            if a is b:
                continue
            same = {x["service"] for x in a["affected"]} & {x["service"] for x in b["affected"]}
            if same:
                a0, a1, b0, b1 = (pd.Timestamp(x) for x in (a["start"], a["end"], b["start"], b["end"]))
                assert a1 <= b0 or b1 <= a0


def test_labels_deterministic():
    cfg = load_sim_config(days=3, rate_scale=0.3)
    assert simulate(cfg)[3] == simulate(cfg)[3]


def test_latency_spike_multiplies_p95(sim):
    cfg, _, req, _, labels = sim
    f = first(labels, "latency_spike")
    ep = cfg.endpoint_index(f["service"], f["endpoint"])
    s, e = window(cfg, f)
    st = minute_stats(cfg, req, ep)
    inside, before = st.loc[s:e - 1, "p95"].median(), st.loc[s - 60:s - 10, "p95"].median()
    assert inside / before > 2.5


def test_error_burst_hits_target_rate(sim):
    cfg, _, req, _, labels = sim
    f = first(labels, "error_burst")
    ep = cfg.endpoint_index(f["service"], f["endpoint"])
    s, e = window(cfg, f)
    st = minute_stats(cfg, req, ep)
    assert st.loc[s:e - 1, "err"].mean() == pytest.approx(f["severity"], abs=0.06)


def test_dependency_outage_cascades_with_lag(sim):
    cfg, _, req, _, labels = sim
    f = first(labels, "dependency_outage")
    assert [a["service"] for a in f["affected"]] == ["inventory", "orders", "gateway"]
    starts = [a["start_min"] for a in f["affected"]]
    assert starts[0] < starts[1] < starts[2]
    assert 1 <= starts[1] - starts[0] <= 2 and starts[2] - starts[1] >= 1
    ep = cfg.endpoint_index("orders", "POST /orders")
    st = minute_stats(cfg, req, ep)
    assert st.loc[starts[1] + 1: f["affected"][0]["start_min"] + 4, "err"].mean() > 0.5


def test_latency_drift_climbs_then_resets(sim):
    cfg, _, req, _, labels = sim
    f = first(labels, "latency_drift")
    ep = cfg.endpoint_index(f["service"], f["endpoint"])
    s, e = window(cfg, f)
    p95 = minute_stats(cfg, req, ep)["p95"].rolling(30, min_periods=10).median()
    assert p95.loc[e - 5] > 1.6 * p95.loc[s + 20]
    assert p95.loc[e + 60] < 0.7 * p95.loc[e - 5]


def test_traffic_drop_reduces_rate(sim):
    cfg, params, _, _, labels = sim
    f = first(labels, "traffic_drop")
    ep = cfg.endpoint_index(f["service"], f["endpoint"])
    s, e = window(cfg, f)
    ratio = params.rate[s:e, ep].mean() / params.rate[s - 120:s - 20, ep].mean()
    assert ratio < 1 - f["severity"] + 0.35


def test_novel_error_stays_under_slo_and_adds_template(sim):
    cfg, params, req, logs, labels = sim
    for f in labels["faults"]:
        if f["type"] == "novel_error":
            ep = cfg.endpoint_index(f["service"], f["endpoint"])
            s, e = window(cfg, f)
            assert (params.err[s:e, ep] + params.novel_rate[s:e, ep]).max() < 0.01
    f = first(labels, "novel_error")
    novel = logs[logs["tid"].str.contains("err_novel") & (logs["service"] == f["service"])]
    t0, t1 = [cfg.start.value // 1_000_000 + m * 60_000 for m in window(cfg, f)]
    assert len(novel) > 0
    mine = novel[(novel["ts"] >= t0) & (novel["ts"] < t1)]
    assert len(mine) > 0


def test_deploy_swaps_error_template_wording(sim):
    cfg, _, _, logs, labels = sim
    d = labels["benign"][[b["type"] for b in labels["benign"]].index("deploy")]
    t0, t1 = [cfg.start.value // 1_000_000 + m * 60_000 for m in window(cfg, d)]
    inside = logs[(logs["ts"] >= t0) & (logs["ts"] < t1) & (logs["service"] == d["service"])]
    assert inside["tid"].str.contains(r"\.deploy\.").any()
    variants = logs[logs["tid"].str.endswith(".v2")]
    assert len(variants) > 0
    for svc, grp in variants.groupby("service"):
        wins = [window(cfg, x) for x in labels["benign"] if x["type"] == "deploy" and x["service"] == svc]
        ok = np.zeros(len(grp), dtype=bool)
        for lo, hi in wins:
            t_lo, t_hi = [cfg.start.value // 1_000_000 + m * 60_000 for m in (lo, hi)]
            ok |= grp["ts"].between(t_lo, t_hi - 1).to_numpy()
        assert ok.all()


def test_traffic_surge_doubles_rate(sim):
    from lighthouse.sim.traffic import minute_index, seasonal_shape

    cfg, params, _, _, labels = sim
    b = next(x for x in labels["benign"] if x["type"] == "traffic_surge")
    s, e = window(cfg, b)
    assert e - s == 60
    shape = seasonal_shape(minute_index(cfg), cfg)[s:e]
    peak = cfg.endpoints[0].peak_rate
    ratio = params.rate[s:e, 0].sum() / (shape.sum() * peak)
    assert ratio == pytest.approx(2.0, rel=0.15)

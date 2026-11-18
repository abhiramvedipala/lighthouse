import numpy as np
import pandas as pd
import pytest

from lighthouse.aggregate import aggregate, aggregate_dir, mine_signatures
from tests.test_fixture import FIX

START = pd.Timestamp("2026-10-05")
START_MS = START.value // 1_000_000
EPS = [("gateway", "GET /products"), ("orders", "POST /orders")]


def req_rows(minute, ep, latencies, statuses=None):
    statuses = statuses or [200] * len(latencies)
    svc, endpoint = EPS[ep]
    return [
        {"ts": START_MS + minute * 60_000 + i * 1000, "service": svc, "endpoint": endpoint,
         "latency_ms": float(lat), "status": st}
        for i, (lat, st) in enumerate(zip(latencies, statuses, strict=True))
    ]


def log_row(minute, svc, ep, level, msg):
    return {"ts": START_MS + minute * 60_000 + 500, "service": svc, "endpoint": ep, "level": level, "message": msg}


@pytest.fixture
def tiny():
    lat = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    rows = req_rows(0, 0, lat, [200] * 8 + [500, 503]) + req_rows(2, 0, [5, 15])
    req = pd.DataFrame(rows)
    logs = pd.DataFrame([
        log_row(0, "gateway", "GET /products", "ERROR", "database timeout after 15ms OperationalError"),
        log_row(0, "gateway", "GET /products", "ERROR", "database timeout after 99ms OperationalError"),
        log_row(0, "gateway", "GET /products", "WARN", "slow upstream response took 700ms"),
        log_row(0, "gateway", "GET /products", "INFO", "request handled"),
        log_row(2, "gateway", "GET /products", "ERROR", "ledger conflict LedgerConflictError"),
    ])
    return aggregate(req, logs, EPS, START, 5)


def row(df, ep, minute):
    svc, endpoint = EPS[ep]
    return df[(df.service == svc) & (df.endpoint == endpoint) & (df.ts == START + pd.Timedelta(minutes=minute))].iloc[0]


def test_counts_and_error_rate_match_hand_computation(tiny):
    r = row(tiny, 0, 0)
    assert (r.request_count, r.error_count) == (10, 2)
    assert r.error_rate == pytest.approx(0.2)


def test_percentiles_match_numpy_linear(tiny):
    r = row(tiny, 0, 0)
    lat = np.arange(10, 101, 10)
    assert r.p50_ms == pytest.approx(np.percentile(lat, 50))
    assert r.p95_ms == pytest.approx(np.percentile(lat, 95))
    assert r.p99_ms == pytest.approx(np.percentile(lat, 99))


def test_empty_minutes_are_rows_with_zero_count_and_null_latency(tiny):
    assert len(tiny) == 5 * len(EPS)
    r = row(tiny, 0, 1)
    assert r.request_count == 0 and r.error_rate == 0 and np.isnan(r.p95_ms)


def test_warn_error_lines_and_distinct_signatures(tiny):
    r = row(tiny, 0, 0)
    assert r.warn_error_lines == 3  # two ERROR + one WARN, the INFO line is not counted
    assert r.distinct_error_sigs == 1  # both errors are the same template and exception


def test_new_signature_feature_counts_from_first_appearance(tiny):
    assert row(tiny, 0, 0).new_sigs_24h == 1
    assert row(tiny, 0, 1).new_sigs_24h == 1  # still inside 24 h, nothing new but it stays counted
    assert row(tiny, 0, 2).new_sigs_24h == 2
    assert row(tiny, 1, 0).new_sigs_24h == 0  # other endpoint


def test_new_signature_expires_after_24_hours():
    minutes = 1440 * 2 + 10
    logs = pd.DataFrame([log_row(10, "gateway", "GET /products", "ERROR", "boom TimeoutError")])
    req = pd.DataFrame(req_rows(0, 0, [1]))
    df = aggregate(req, logs, EPS[:1], START, minutes)
    got = df.set_index(df.ts).new_sigs_24h
    assert got[START + pd.Timedelta(minutes=9)] == 0
    assert got[START + pd.Timedelta(minutes=10)] == 1
    assert got[START + pd.Timedelta(minutes=10 + 1439)] == 1
    assert got[START + pd.Timedelta(minutes=10 + 1440)] == 0


def test_new_signature_feature_uses_only_the_past():
    """Features up to minute m are identical when every later log line is removed."""
    req = pd.read_parquet(FIX / "requests.parquet")
    from lighthouse.aggregate import load_logs

    logs = load_logs(FIX / "logs.jsonl.gz")
    cut = 1000
    eps = sorted(set(zip(req.service, req.endpoint, strict=True)))
    start = pd.Timestamp(req["ts"].min() // 60_000 * 60_000, unit="ms")
    full = aggregate(req, logs, eps, start, 1440 * 2)
    cut_ms = int(start.value // 1_000_000) + cut * 60_000
    part = aggregate(req[req.ts < cut_ms], logs[logs.ts < cut_ms], eps, start, cut)
    a = full[full.ts < start + pd.Timedelta(minutes=cut)].reset_index(drop=True)
    b = part.reset_index(drop=True)
    cols = ["request_count", "warn_error_lines", "distinct_error_sigs", "new_sigs_24h"]
    pd.testing.assert_frame_equal(a[cols], b[cols])


def test_fixture_aggregate_shape_and_totals():
    df = aggregate_dir(FIX)
    assert len(df) == 2 * 1440 * 5
    req = pd.read_parquet(FIX / "requests.parquet")
    assert df.request_count.sum() == len(req)
    assert df.error_count.sum() == (req.status >= 500).sum()


def test_mine_signatures_flags_only_first_occurrence():
    logs = pd.DataFrame([
        log_row(0, "orders", "POST /orders", "ERROR", "db timeout 5ms OperationalError"),
        log_row(1, "orders", "POST /orders", "ERROR", "db timeout 9ms OperationalError"),
        log_row(2, "gateway", "GET /products", "ERROR", "db timeout 9ms OperationalError"),
    ])
    sigs = mine_signatures(logs)
    assert sigs["is_new"].tolist() == [True, False, True]  # same text, different service: separate signature

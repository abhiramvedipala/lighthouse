import json

import numpy as np

from lighthouse.live import LiveSeasonal, Windower, static_score
from lighthouse.otlp import decode_logs, decode_spans
from lighthouse.stream import Metrics, StreamProcessor

W = 10_000  # window length in ms


def span_msg(service, endpoint, end_ms, dur_ms, status=200):
    return json.dumps({"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeSpans": [{"spans": [{
            "name": endpoint, "startTimeUnixNano": str(int((end_ms - dur_ms) * 1e6)), "endTimeUnixNano": str(int(end_ms * 1e6)),
            "attributes": [{"key": "http.status_code", "value": {"intValue": str(status)}},
                           {"key": "service.endpoint", "value": {"stringValue": endpoint}}],
            "status": {"code": 2 if status >= 500 else 0}}]}]}]})


def log_msg(service, endpoint, ts_ms, level, body):
    return json.dumps({"resourceLogs": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
        "scopeLogs": [{"logRecords": [{
            "timeUnixNano": str(int(ts_ms * 1e6)), "severityText": level, "body": {"stringValue": body},
            "attributes": [{"key": "lighthouse.endpoint", "value": {"stringValue": endpoint}}]}]}]}]})


def test_decode_spans_and_logs():
    sp = decode_spans(span_msg("gateway", "GET /products", 5000, 40, 503))[0]
    assert (sp.service, sp.endpoint, sp.error, sp.status) == ("gateway", "GET /products", True, 503)
    assert abs(sp.duration_ms - 40) < 1e-6 and sp.end_ms == 5000
    lg = decode_logs(log_msg("orders", "POST /orders", 7000, "ERROR", "boom TimeoutError"))[0]
    assert (lg.service, lg.level, lg.endpoint, lg.ts_ms) == ("orders", "ERROR", "POST /orders", 7000)


def test_windower_buckets_by_ten_seconds_and_holds_back_the_open_window():
    w = Windower()
    for i, end in enumerate((1000, 9000, 12000, 25000)):
        w.add_span(decode_spans(span_msg("gateway", "GET /products", end, 10 + i))[0])
    rows = w.pop_ready(now_ms=35_000)   # windows 0,1,2 exist; current is 3, grace 1 -> only < 2 are ready
    assert [r["window"] for r in rows] == [0, 1]
    assert rows[0]["n"] == 2 and rows[1]["n"] == 1
    assert len(w.cells) == 1            # window 2 still open


def test_static_score_needs_six_bad_windows():
    import pandas as pd

    bad = pd.DataFrame({"n": [10] * 6, "errs": [2] * 6, "p95": [50.0] * 6})
    assert static_score(bad, 250) >= 1.0
    assert static_score(bad.head(5), 250) == 0.0
    ok = bad.assign(errs=[2, 2, 0, 2, 2, 2])
    assert static_score(ok, 250) < 1.0


def feed(proc, window, rate, err_frac=0.0, lat=40.0, services=(("gateway", "GET /products"), ("orders", "POST /orders"))):
    t0 = window * W
    for svc, ep in services:
        for i in range(rate):
            ts = t0 + 500 + i * (W - 1000) // max(rate, 1)
            status = 500 if (i < int(rate * err_frac)) else 200
            proc.on_message("otlp_spans", span_msg(svc, ep, ts, lat * (1 + 0.05 * (i % 3)), status))
        if err_frac:
            proc.on_message("otlp_logs", log_msg(svc, ep, t0 + 800, "ERROR", f"database timeout after {window}ms OperationalError"))


def run_scenario(fault_window=70, n_windows=80):
    proc = StreamProcessor(warmup_windows=48, day_seconds=120, metrics=Metrics(), clock=lambda: 0)
    scored = []
    rng = np.random.default_rng(0)
    for win in range(n_windows):
        shape = 1 + 0.5 * np.sin(2 * np.pi * (win % 12) / 12)
        rate = int(20 * shape) + int(rng.integers(0, 2))
        faulty = fault_window <= win < fault_window + 8
        feed(proc, win, rate, err_frac=0.5 if faulty else 0.0, lat=40.0 * (6 if faulty else 1))
        scored += proc.tick(now_ms=(win + 3) * W)
    return proc, scored


def test_warmup_then_scores_and_flags_a_fault_but_not_normal_windows():
    proc, scored = run_scenario()
    assert proc.fitted and proc.n_messages > 1000
    assert scored and not any(s.flag for s in scored if s.window < 68)       # quiet before the fault
    hits = {s.detector for s in scored if s.flag and s.window >= 70}
    assert "seasonal_baseline" in hits and "static_threshold" in hits


def test_nothing_is_scored_during_warmup():
    proc = StreamProcessor(warmup_windows=48, day_seconds=120, metrics=Metrics(), clock=lambda: 0)
    out = []
    for win in range(30):
        feed(proc, win, 20)
        out += proc.tick(now_ms=(win + 3) * W)
    assert not proc.fitted and out == []


def test_metrics_expose_scores_flags_counts_and_lag():
    proc, _ = run_scenario()
    from prometheus_client import generate_latest

    text = generate_latest(proc.metrics.registry).decode()
    assert 'lighthouse_anomaly_score{detector="seasonal_baseline",endpoint="GET /products",service="gateway"}' in text
    assert "lighthouse_anomaly_flag" in text and 'lighthouse_events_total{topic="otlp_spans"}' in text
    assert "lighthouse_score_lag_seconds_count" in text and "lighthouse_ingest_lag_seconds_count" in text


def test_error_signatures_are_tracked_and_template_state_persists(tmp_path):
    proc = StreamProcessor(state_dir=tmp_path, warmup_windows=1000, metrics=Metrics(), clock=lambda: 0)
    proc.on_message("otlp_logs", log_msg("orders", "POST /orders", 1000, "ERROR", "database timeout after 5ms OperationalError"))
    proc.on_message("otlp_logs", log_msg("orders", "POST /orders", 2000, "ERROR", "database timeout after 9ms OperationalError"))
    assert len(proc.book.first_seen) == 1
    proc.save()
    again = StreamProcessor(state_dir=tmp_path, warmup_windows=1000, metrics=Metrics(), clock=lambda: 0)
    assert again.book.first_seen == proc.book.first_seen
    assert again.store("orders").templates() == proc.store("orders").templates()


def test_live_seasonal_scores_a_drop_in_rate():
    import pandas as pd

    rows = [{"window": w, "service": "s", "endpoint": "e", "n": 20 + (w % 12), "errs": 0, "p95": 40.0, "warn": 0, "new_sigs": 0}
            for w in range(60)]
    model = LiveSeasonal(day_seconds=120).fit(pd.DataFrame(rows))
    normal = pd.DataFrame(rows[-5:])
    drop = normal.copy()
    drop["n"] = 2
    assert model.score(("s", "e"), drop) > 3 * max(model.score(("s", "e"), normal), 0.3)


def test_hostile_input_is_dropped_not_fatal(tmp_path, monkeypatch):
    from lighthouse.stream import default_state_dir

    proc = StreamProcessor(warmup_windows=10**6, metrics=Metrics(), clock=lambda: 0)
    proc.on_message("otlp_logs", b"not json")
    proc.on_message("otlp_spans", span_msg("../../etc", "GET /x", 1000, 5))     # path-like service name
    proc.on_message("otlp_spans", span_msg("gateway", "GET /x", 10**13, 5))     # absurd timestamp
    assert proc.dropped == 3 and not proc.windower.cells
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    d = default_state_dir()
    assert d.startswith(str(tmp_path)) and oct(__import__("os").stat(d).st_mode & 0o777) == "0o700"


def test_unknown_endpoints_after_warmup_are_skipped():
    proc, _ = run_scenario()
    feed(proc, 90, 10, services=(("gateway", "GET /never-seen"),))
    assert proc.tick(now_ms=93 * W) == [] or all(s.endpoint != "GET /never-seen" for s in proc.tick(now_ms=95 * W))

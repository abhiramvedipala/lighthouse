"""Streaming consumer: Kafka otlp_logs and otlp_spans -> 10 s windows -> live detectors -> /metrics.

`StreamProcessor` holds all logic and is driven by plain method calls in tests; `run()` is the thin
confluent-kafka loop around it. Exposed gauges: lighthouse_anomaly_score{service,endpoint,detector},
lighthouse_anomaly_flag{...}; plus consumer lag and throughput.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lighthouse.live import WINDOW_S, LiveForest, LiveSeasonal, Tail, Windower, static_score
from lighthouse.otlp import decode_logs, decode_spans
from lighthouse.parse.templates import SIM_PIPELINE_SIM_TH, SignatureBook, TemplateStore
from lighthouse.sim.config import load_slo

SEASONAL_THRESHOLD = 2.2   # offline validation threshold (results/thresholds.json), same normalisation
TOPICS = ("otlp_logs", "otlp_spans")


@dataclass
class Scored:
    window: int
    service: str
    endpoint: str
    detector: str
    score: float
    flag: bool


class Metrics:
    def __init__(self, registry=None):
        from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

        self.registry = registry or CollectorRegistry()
        kw = {"registry": self.registry}
        self.score = Gauge("lighthouse_anomaly_score", "detector score", ["service", "endpoint", "detector"], **kw)
        self.flag = Gauge("lighthouse_anomaly_flag", "1 when the score is over the threshold",
                          ["service", "endpoint", "detector"], **kw)
        self.events = Counter("lighthouse_events_total", "OTLP messages consumed", ["topic"], **kw)
        self.lag = Histogram("lighthouse_ingest_lag_seconds", "wall clock minus record timestamp at ingest",
                             buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30), **kw)
        self.score_lag = Histogram("lighthouse_score_lag_seconds", "wall clock at scoring minus window end",
                                   buckets=(5, 10, 15, 20, 30, 60), **kw)
        self.windows = Counter("lighthouse_windows_scored_total", "endpoint windows scored", **kw)


class StreamProcessor:
    def __init__(self, state_dir: Path | str | None = None, warmup_windows: int = 360, day_seconds: float = 1200,
                 metrics: Metrics | None = None, clock=time.time):
        self.state_dir = Path(state_dir) if state_dir else None
        self.warmup, self.day_seconds, self.clock = warmup_windows, day_seconds, clock
        self.metrics = metrics or Metrics()
        self.slo = {k: v["p95_ms"] for k, v in load_slo().items()}
        self.windower, self.tail = Windower(), Tail()
        self.stores: dict[str, TemplateStore] = {}
        self.book = SignatureBook.load(self.state_dir / "signatures.json") if self.state_dir else SignatureBook()
        self.history: list[dict] = []
        self.seasonal: LiveSeasonal | None = None
        self.forest: LiveForest | None = None
        self.n_messages = 0

    # ---- ingest ----------------------------------------------------------------------------------
    def store(self, service: str) -> TemplateStore:
        if service not in self.stores:
            path = self.state_dir / f"drain_{service}.state" if self.state_dir else None
            self.stores[service] = TemplateStore(path, sim_th=SIM_PIPELINE_SIM_TH)
        return self.stores[service]

    def on_message(self, topic: str, raw: bytes | str) -> None:
        now = self.clock() * 1000
        self.n_messages += 1
        self.metrics.events.labels(topic).inc()
        if topic == "otlp_spans":
            for sp in decode_spans(raw):
                self.metrics.lag.observe(max(now - sp.end_ms, 0) / 1000)
                self.windower.add_span(sp)
        elif topic == "otlp_logs":
            for rec in decode_logs(raw):
                self.metrics.lag.observe(max(now - rec.ts_ms, 0) / 1000)
                tid = self.store(rec.service).add(rec.body)
                if rec.level == "ERROR":
                    sig, new = self.book.observe(rec.service, tid, rec.body, rec.ts_ms)
                    self.windower.add_log(rec, sig.key(), new)
                else:
                    self.windower.add_log(rec, None, False)

    # ---- scoring ---------------------------------------------------------------------------------
    def fit(self) -> None:
        hist = pd.DataFrame(self.history)
        self.seasonal = LiveSeasonal(self.day_seconds).fit(hist)
        self.forest = LiveForest(self.seasonal).fit(hist)

    @property
    def fitted(self) -> bool:
        return self.seasonal is not None

    def tick(self, now_ms: int | None = None) -> list[Scored]:
        now_ms = int(self.clock() * 1000) if now_ms is None else now_ms
        out: list[Scored] = []
        for row in self.windower.pop_ready(now_ms):
            if not self.fitted:
                self.history.append(row)
                if len({r["window"] for r in self.history}) >= self.warmup:
                    self.fit()
                continue
            key = (row["service"], row["endpoint"])
            hist = self.tail.add(row)
            scores = {
                "static_threshold": (static_score(hist, self.slo[key]), 1.0),
                "seasonal_baseline": (self.seasonal.score(key, hist), SEASONAL_THRESHOLD),
            }
            if len(hist) >= 2:
                svc_hist = pd.DataFrame([r for k, q in self.tail.rows.items() if k[0] == key[0] for r in q])
                scores["isolation_forest"] = (self.forest.score(svc_hist, key[0]), self.forest.threshold[key[0]])
            for det, (sc, thr) in scores.items():
                s = Scored(row["window"], key[0], key[1], det, float(sc), bool(sc > thr))
                out.append(s)
                self.metrics.score.labels(key[0], key[1], det).set(s.score)
                self.metrics.flag.labels(key[0], key[1], det).set(float(s.flag))
            self.metrics.windows.inc()
            self.metrics.score_lag.observe(max(now_ms - (row["window"] + 1) * WINDOW_S * 1000, 0) / 1000)
        return out

    def save(self) -> None:
        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            for st in self.stores.values():
                st.save()
            self.book.save(self.state_dir / "signatures.json")


def run(bootstrap: str, group: str = "lighthouse", port: int = 9108, state_dir: str = "/tmp/lighthouse-state",
        warmup_windows: int = 360, day_seconds: float = 1200, log=print) -> None:  # pragma: no cover - needs Kafka
    from confluent_kafka import Consumer
    from prometheus_client import start_http_server

    proc = StreamProcessor(state_dir, warmup_windows, day_seconds)
    start_http_server(port, registry=proc.metrics.registry)
    c = Consumer({"bootstrap.servers": bootstrap, "group.id": group, "auto.offset.reset": "latest",
                  "enable.auto.commit": True})
    c.subscribe(list(TOPICS))
    last_tick = last_save = time.time()
    log(f"consuming {TOPICS} from {bootstrap}, metrics on :{port}")
    while True:
        msg = c.poll(0.5)
        if msg is not None and not msg.error():
            proc.on_message(msg.topic(), msg.value())
        now = time.time()
        if now - last_tick >= 1:
            last_tick = now
            for s in proc.tick():
                if s.flag:
                    log(json.dumps({"window": s.window, "service": s.service, "endpoint": s.endpoint,
                                    "detector": s.detector, "score": round(s.score, 2)}))
        if now - last_save >= 30:
            last_save = now
            proc.save()


def main() -> None:  # pragma: no cover
    import argparse
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", default=os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"))
    ap.add_argument("--port", type=int, default=9108)
    ap.add_argument("--state-dir", default=os.environ.get("STATE_DIR", "/tmp/lighthouse-state"))
    ap.add_argument("--warmup-windows", type=int, default=360)
    a = ap.parse_args()
    run(a.bootstrap, port=a.port, state_dir=a.state_dir, warmup_windows=a.warmup_windows)


if __name__ == "__main__":
    main()

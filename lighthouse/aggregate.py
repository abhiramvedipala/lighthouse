"""Per (service, endpoint, minute) aggregates with DuckDB over parquet. See docs/schema.md.

    uv run python -m lighthouse.aggregate --source sim            # data/sim -> data/sim/aggregates.parquet
    uv run python -m lighthouse.aggregate --source fixture        # the committed 2-day fixture
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from lighthouse.parse.templates import SIM_PIPELINE_SIM_TH, SignatureBook, TemplateStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sim2d"
SIM_DIR = ROOT / "data" / "sim"
DAY_MS = 86_400_000

COLUMNS = [
    "ts", "service", "endpoint", "request_count", "error_count", "error_rate", "p50_ms", "p95_ms", "p99_ms",
    "warn_error_lines", "distinct_error_sigs", "new_sigs_24h",
]


def load_logs(path: Path) -> pd.DataFrame:
    """Read logs.jsonl(.gz) into a frame with an int64 epoch-ms `ts` column."""
    df = pd.read_json(path, lines=True)
    stamp = pd.to_datetime(df["timestamp"], utc=True)  # unit varies by pandas version, so divide by a Timedelta
    df["ts"] = ((stamp - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).astype("int64")
    return df.drop(columns=["timestamp"])


def mine_signatures(logs: pd.DataFrame, sim_th: float = SIM_PIPELINE_SIM_TH) -> pd.DataFrame:
    """Run Drain per service over all lines in time order; return one row per ERROR line.

    Columns: ts, service, endpoint, template_id, exception, sig (string key), is_new (first
    occurrence of that signature in the stream).
    """
    logs = logs.sort_values("ts", kind="stable").reset_index(drop=True)
    stores = {s: TemplateStore(sim_th=sim_th) for s in logs["service"].unique()}
    book = SignatureBook()
    rows = []
    for ts, svc, lvl, msg, ep in zip(
        logs["ts"].tolist(), logs["service"].tolist(), logs["level"].tolist(),
        logs["message"].tolist(), logs["endpoint"].tolist(), strict=True,
    ):
        tid = stores[svc].add(msg)
        if lvl == "ERROR":
            sig, new = book.observe(svc, tid, msg, ts)
            rows.append((ts, svc, ep, tid, sig.exception, sig.key(), new))
    return pd.DataFrame(rows, columns=["ts", "service", "endpoint", "template_id", "exception", "sig", "is_new"])


def aggregate(
    requests: pd.DataFrame,
    logs: pd.DataFrame,
    endpoints: Sequence[tuple[str, str]],
    start: pd.Timestamp,
    minutes: int,
    sim_th: float = SIM_PIPELINE_SIM_TH,
) -> pd.DataFrame:
    """requests needs ts (epoch ms), service, endpoint, latency_ms, status."""
    start_ms = int(pd.Timestamp(start).value // 1_000_000)  # naive timestamps are UTC
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'; SET threads=4")
    grid = pd.DataFrame(
        [(s, e, m) for s, e in endpoints for m in range(minutes)], columns=["service", "endpoint", "minute"]
    )
    req = requests[["ts", "service", "endpoint", "latency_ms", "status"]].copy()
    req["minute"] = ((req["ts"] - start_ms) // 60_000).astype("int64")
    con.register("grid", grid)
    con.register("req", req)
    base = con.execute(
        """
        SELECT g.service, g.endpoint, g.minute,
               COALESCE(r.n, 0)::INT AS request_count,
               COALESCE(r.errs, 0)::INT AS error_count,
               r.p50, r.p95, r.p99
        FROM grid g LEFT JOIN (
            SELECT service, endpoint, minute, count(*) AS n, sum((status >= 500)::INT) AS errs,
                   quantile_cont(latency_ms, 0.5) AS p50, quantile_cont(latency_ms, 0.95) AS p95,
                   quantile_cont(latency_ms, 0.99) AS p99
            FROM req GROUP BY ALL) r USING (service, endpoint, minute)
        """
    ).df()

    sigs = mine_signatures(logs, sim_th)
    lg = logs[["ts", "service", "endpoint", "level"]].copy()
    lg["minute"] = ((lg["ts"] - start_ms) // 60_000).astype("int64")
    we = (
        lg[lg["level"].isin(["WARN", "ERROR"])]
        .groupby(["service", "endpoint", "minute"]).size().rename("warn_error_lines").reset_index()
    )
    sigs["minute"] = ((sigs["ts"] - start_ms) // 60_000).astype("int64")
    distinct = (
        sigs.groupby(["service", "endpoint", "minute"])["sig"].nunique().rename("distinct_error_sigs").reset_index()
    )
    out = base.merge(we, how="left", on=["service", "endpoint", "minute"]).merge(
        distinct, how="left", on=["service", "endpoint", "minute"]
    )
    count_cols = ["warn_error_lines", "distinct_error_sigs"]
    out[count_cols] = out[count_cols].fillna(0).astype(int)

    # new_sigs_24h: signatures whose first occurrence was on this endpoint within 24h up to minute end
    first = sigs[sigs["is_new"]][["service", "endpoint", "minute"]]
    new_sigs = np.zeros(len(out), dtype=np.int32)
    out = out.sort_values(["service", "endpoint", "minute"]).reset_index(drop=True)
    pos = 0
    for (svc, ep), grp in out.groupby(["service", "endpoint"], sort=False):
        counts = np.zeros(minutes, dtype=np.int32)
        f = first[(first["service"] == svc) & (first["endpoint"] == ep)]["minute"].to_numpy()
        np.add.at(counts, f, 1)
        csum = np.concatenate([[0], np.cumsum(counts)])
        m = grp["minute"].to_numpy()
        lo = np.maximum(m - 1440 + 1, 0)  # a signature first seen in minute k counts for minutes k..k+1439
        new_sigs[pos:pos + len(grp)] = csum[m + 1] - csum[lo]
        pos += len(grp)
    out["new_sigs_24h"] = new_sigs
    out["ts"] = pd.Timestamp(start_ms, unit="ms") + pd.to_timedelta(out["minute"], unit="min")
    out["error_rate"] = np.where(out["request_count"] > 0, out["error_count"] / out["request_count"].clip(lower=1), 0.0)
    out = out.rename(columns={"p50": "p50_ms", "p95": "p95_ms", "p99": "p99_ms"})
    return out[COLUMNS].sort_values(["service", "endpoint", "ts"]).reset_index(drop=True)


def aggregate_dir(src: Path, endpoints=None, start=None, minutes=None) -> pd.DataFrame:
    """Aggregate a simulator output directory (requests.parquet + logs.jsonl[.gz])."""
    from lighthouse.sim.config import load_sim_config

    req = pd.read_parquet(src / "requests.parquet")
    log_path = next(p for p in (src / "logs.jsonl", src / "logs.jsonl.gz") if p.exists())
    logs = load_logs(log_path)
    if endpoints is None:
        cfg = load_sim_config()
        endpoints = [(e.service, e.endpoint) for e in cfg.endpoints]
    if start is None or minutes is None:
        t0 = req["ts"].min() // 60_000 * 60_000
        start = pd.Timestamp(t0, unit="ms")
        minutes = int((req["ts"].max() - t0) // 60_000) + 1
        # whole days: the simulator always writes complete days
        minutes = -(-minutes // 1440) * 1440
    return aggregate(req, logs, endpoints, start, minutes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("sim", "fixture"), default="sim")
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    src = a.dir or (SIM_DIR if a.source == "sim" else FIXTURE_DIR)
    t0 = time.perf_counter()
    df = aggregate_dir(src)
    out = a.out or (src / "aggregates.parquet" if a.source == "sim" else ROOT / "data" / "fixture_aggregates.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"{len(df)} rows ({df['service'].nunique()} services, {df['endpoint'].nunique()} endpoints) -> {out} "
          f"in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()

"""Synthetic datasets for detector tests."""
import numpy as np
import pandas as pd

from lighthouse.data import Dataset

SLO = {"p95_ms": 100.0, "error_rate": 0.01}


def make_ds(minutes=600, services=(("svc", "GET /x"),), count=None, errs=None, p95=None, labels=None,
            start="2026-10-05", seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for svc, ep in services:
        n = np.full(minutes, 100) if count is None else np.asarray(count)
        e = np.zeros(minutes, dtype=int) if errs is None else np.asarray(errs)
        lat = np.full(minutes, 40.0) if p95 is None else np.asarray(p95, dtype=float)
        lat = lat + rng.normal(0, 0.01, minutes)
        rows.append(pd.DataFrame({
            "ts": pd.date_range(start, periods=minutes, freq="min"), "service": svc, "endpoint": ep,
            "request_count": n, "error_count": e, "error_rate": np.where(n > 0, e / np.maximum(n, 1), 0.0),
            "p50_ms": lat * 0.5, "p95_ms": np.where(n > 0, lat, np.nan), "p99_ms": lat * 1.2,
            "warn_error_lines": 0, "distinct_error_sigs": 0, "new_sigs_24h": 0,
        }))
    agg = pd.concat(rows, ignore_index=True)
    slo = {s: SLO for s in services}
    return Dataset(agg, pd.Timestamp(start), minutes, labels or {"faults": [], "benign": []}, slo)

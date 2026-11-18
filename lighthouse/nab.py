"""External sanity check on the Numenta Anomaly Benchmark (NAB).

Each NAB series (5-minute points) is forward-filled to 1-minute rows and mapped onto the same
aggregate schema (value -> request_count and p95_ms, so both a drop and a rise are visible), then the
seasonal baseline, Isolation Forest and Prophet run through the same fit/score/evaluate code. NAB's
labeled windows become incidents. Splits: first 35% train, next 25% validation, last 40% test.
With few labeled windows there is no labeled validation signal, so the threshold is the 99.9th
percentile of the detector's own validation-window scores (no labels used). This is window-level
precision and recall with this repo's evaluation, not the official NAB score, because that score
needs per-profile weights and a different window convention.

    uv run python -m lighthouse.nab
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from lighthouse.data import Dataset
from lighthouse.detectors.iforest import IsolationForestDetector
from lighthouse.detectors.prophet_residual import ProphetResidual
from lighthouse.detectors.seasonal import SeasonalBaseline
from lighthouse.evaluate import evaluate
from lighthouse.thresholds import flags_from_scores

ROOT = Path(__file__).resolve().parents[1]
NAB_DIR = ROOT / "data" / "nab"
FILES = {
    "machine_temperature_system_failure": "realKnownCause/machine_temperature_system_failure.csv",
    "ec2_cpu_utilization_825cc2": "realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv",
    "rds_cpu_utilization_cc0c53": "realAWSCloudwatch/rds_cpu_utilization_cc0c53.csv",
    "elb_request_count_8c0756": "realAWSCloudwatch/elb_request_count_8c0756.csv",
}
FRACS = (0.35, 0.25)


def to_dataset(values: pd.Series, windows: list[list[str]]) -> Dataset:
    """values indexed by timestamp (5-minute points) -> Dataset with one service/endpoint."""
    values = values[~values.index.duplicated(keep="last")].sort_index()  # NAB has a few repeated stamps
    idx = pd.date_range(values.index.min(), values.index.max() + pd.Timedelta(minutes=4), freq="min")
    v = values.reindex(idx, method="ffill").clip(lower=0.0)
    n = len(idx)
    agg = pd.DataFrame({
        "ts": idx, "service": "nab", "endpoint": "series",
        "request_count": np.round(v.to_numpy() * 10).astype(int), "error_count": 0, "error_rate": 0.0,
        "p50_ms": v.to_numpy() + 1.0, "p95_ms": v.to_numpy() + 1.0, "p99_ms": v.to_numpy() + 1.0,
        "warn_error_lines": 0, "distinct_error_sigs": 0, "new_sigs_24h": 0,
    })
    events = [{"id": f"w{i}", "type": "nab_window", "service": "nab", "endpoint": "series", "start": str(pd.Timestamp(a)),
               "end": str(pd.Timestamp(b)), "severity": 0.0,
               "affected": [{"service": "nab", "endpoint": "series", "start": str(pd.Timestamp(a))}]}
              for i, (a, b) in enumerate(windows)]
    return Dataset(agg, idx[0], n, {"faults": events, "benign": []}, {}, fracs=FRACS)


def run_file(name: str, rel: str, windows: dict) -> list[dict]:
    df = pd.read_csv(NAB_DIR / f"{name}.csv", parse_dates=["timestamp"]).set_index("timestamp")["value"]
    ds = to_dataset(df, windows[rel])
    lo, hi = ds.splits["test"]
    vlo, vhi = ds.splits["val"]
    rows = []
    for dname, det in (("seasonal_baseline", SeasonalBaseline()),
                       ("isolation_forest", IsolationForestDetector(raw=False, deltas=False, templates=False)),
                       ("prophet_residual", ProphetResidual(uncertainty_samples=50))):
        scores = det.fit(ds, ds.splits["train"]).score(ds)
        thr = float(np.quantile(scores["nab"].to_numpy()[vlo:vhi], 0.999))
        r = evaluate(flags_from_scores(scores, thr), ds.incidents, ds.splits["test"], n_services=1)
        rows.append({"series": name, "detector": dname, "test_windows": r.n_incidents, "detected": round(r.recall * r.n_incidents)
                     if r.n_incidents else 0, "alarm_events": r.n_alarm_events,
                     "precision": None if np.isnan(r.precision) else round(r.precision, 2),
                     "recall": None if np.isnan(r.recall) else round(r.recall, 2), "false_alarms": r.false_alarms,
                     "test_days": round((hi - lo) / 1440, 1)})
    return rows


def main() -> None:
    windows = json.loads((NAB_DIR / "combined_windows.json").read_text())
    rows = [r for name, rel in FILES.items() for r in run_file(name, rel, windows)]
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    Path(ROOT / "results").mkdir(exist_ok=True)
    out.to_csv(ROOT / "results" / "nab.csv", index=False)


if __name__ == "__main__":
    main()

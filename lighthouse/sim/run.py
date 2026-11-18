"""Generate a simulated dataset: python -m lighthouse.sim.run --out data/sim"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from lighthouse.sim.config import load_sim_config
from lighthouse.sim.logs import generate_logs
from lighthouse.sim.traffic import build_params, sample_requests


def simulate(cfg, faults: bool = True):
    """Return (params, requests, logs, labels). Faults are applied when the module exists."""
    r_traffic, r_faults, r_logs = cfg.child_rngs()
    params = build_params(cfg, r_traffic)
    labels = {"faults": [], "benign": []}
    if faults:
        from lighthouse.sim import faults as fmod

        labels = fmod.inject(params, r_faults)
    req = sample_requests(params, r_logs)
    logs = generate_logs(params, req, r_logs)
    return params, req, logs, labels


def write(out: Path, cfg, req, logs, labels) -> None:
    out.mkdir(parents=True, exist_ok=True)
    req = req.copy()
    req["service"] = [cfg.endpoints[i].service for i in req["ep"]]
    req["endpoint"] = [cfg.endpoints[i].endpoint for i in req["ep"]]
    req.drop(columns=["ep"]).to_parquet(out / "requests.parquet", index=False)
    logs = logs.copy()
    logs["timestamp"] = pd.to_datetime(logs["ts"], unit="ms").dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    logs.drop(columns=["ts"]).to_json(out / "logs.jsonl", orient="records", lines=True)
    (out / "labels.json").write_text(json.dumps(labels, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sim")
    ap.add_argument("--config", default=None)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--rate-scale", type=float, default=None)
    ap.add_argument("--no-faults", action="store_true", help="clean traffic only")
    a = ap.parse_args()
    over = {k: v for k, v in (("days", a.days), ("rate_scale", a.rate_scale)) if v is not None}
    cfg = load_sim_config(a.config, **over)
    t0 = time.time()
    _, req, logs, labels = simulate(cfg, faults=not a.no_faults)
    write(Path(a.out), cfg, req, logs, labels)
    print(f"{len(req)} requests, {len(logs)} log lines, {len(labels['faults'])} faults in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

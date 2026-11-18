import json
from pathlib import Path

import pandas as pd

from lighthouse.sim.config import load_sim_config
from lighthouse.sim.run import simulate

FIX = Path(__file__).parent / "fixtures" / "sim2d"


def test_fixture_is_small_and_complete():
    files = {p.name for p in FIX.iterdir()}
    assert files == {"labels.json", "logs.jsonl.gz", "requests.parquet"}
    assert sum(p.stat().st_size for p in FIX.iterdir()) < 5_000_000


def test_fixture_has_every_fault_type_twice():
    labels = json.loads((FIX / "labels.json").read_text())
    types = pd.Series([f["type"] for f in labels["faults"]]).value_counts()
    assert len(types) == 6 and (types >= 2).all()
    assert {b["type"] for b in labels["benign"]} == {"traffic_surge", "deploy"}


def test_fixture_regenerates_identically():
    cfg = load_sim_config(days=2, rate_scale=0.25, seed=7)
    _, req, _, labels = simulate(cfg)
    def norm(x):  # libm differences between macOS and Linux move floats in the last digits
        return json.loads(json.dumps(x), parse_float=lambda f: round(float(f), 6))

    assert norm(labels) == norm(json.loads((FIX / "labels.json").read_text()))
    stored = pd.read_parquet(FIX / "requests.parquet")
    assert len(stored) == len(req)
    assert stored["ts"].iloc[0] == req["ts"].iloc[0]

"""Grid over Drain3 sim_th and depth on HDFS and BGL only (OpenStack and Apache stay untouched).

    uv run python scripts/tune_drain.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lighthouse.parse.bench import grouping_accuracy, load_loghub  # noqa: E402
from lighthouse.parse.templates import drain_parser  # noqa: E402


def tune_sim() -> None:
    """Per-service Drain on simulator logs from the train days (first 7 days) only."""
    import pandas as pd

    from lighthouse.parse.bench import load_sim_logs, parse_grouped

    df = load_sim_logs(ROOT / "data" / "sim")
    ts = pd.to_datetime(pd.read_json(ROOT / "data" / "sim" / "logs.jsonl", lines=True)["timestamp"])
    train = df[ts < ts.min().normalize() + pd.Timedelta(days=7)].reset_index(drop=True)
    print(f"train-day lines: {len(train)}\nsim_th depth accuracy templates")
    for th in (0.5, 0.6, 0.7, 0.8, 0.9):
        for depth in (4, 5):
            pred = parse_grouped(drain_parser(th, depth), train["Content"].tolist(), train["Group"].tolist())
            acc = grouping_accuracy(train["EventId"].tolist(), pred)
            print(f"{th:6} {depth:5} {acc:8.4f} {len(set(pred)):9}")


def main() -> None:
    if "--sim" in sys.argv:
        return tune_sim()
    data = {n: load_loghub(n) for n in ("HDFS", "BGL")}
    print("sim_th depth    HDFS     BGL    mean")
    for th in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        for depth in (4, 5):
            accs = [
                grouping_accuracy(df["EventId"].tolist(), drain_parser(th, depth)(df["Content"].tolist()))
                for df in data.values()
            ]
            print(f"{th:6} {depth:5} " + " ".join(f"{a:7.4f}" for a in accs) + f" {sum(accs) / 2:7.4f}")


if __name__ == "__main__":
    main()

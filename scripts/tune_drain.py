"""Grid over Drain3 sim_th and depth on HDFS and BGL only (OpenStack and Apache stay untouched).

    uv run python scripts/tune_drain.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lighthouse.parse.bench import grouping_accuracy, load_loghub  # noqa: E402
from lighthouse.parse.templates import drain_parser  # noqa: E402


def main() -> None:
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

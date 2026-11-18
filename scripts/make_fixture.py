"""Write the committed CI fixture: a 2-day simulator run with every fault type.

    uv run python scripts/make_fixture.py

Synthetic data, fixed seed, under 5 MB. Rate scale 0.25 keeps it small; the
full 14-day run uses scale 1.0 (see config/sim.yaml).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lighthouse.sim.config import load_sim_config  # noqa: E402
from lighthouse.sim.run import simulate, write  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sim2d"


def main() -> None:
    cfg = load_sim_config(days=2, rate_scale=0.25, seed=7)
    _, req, logs, labels = simulate(cfg)
    write(FIXTURE, cfg, req, logs, labels, gzip_logs=True)
    size = sum(f.stat().st_size for f in FIXTURE.iterdir())
    print(f"fixture: {len(req)} requests, {len(logs)} lines, {len(labels['faults'])} faults, {size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

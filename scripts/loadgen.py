"""python scripts/loadgen.py --minutes 5 [--scale 0.25] [--gateway URL --orders URL --inventory URL]"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lighthouse.loadgen import DAY_SECONDS, run  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=5)
ap.add_argument("--scale", type=float, default=0.25, help="fraction of the simulator's peak rates")
ap.add_argument("--day-seconds", type=float, default=DAY_SECONDS)
ap.add_argument("--gateway", default="http://localhost:8001")
ap.add_argument("--orders", default="http://localhost:8002")
ap.add_argument("--inventory", default="http://localhost:8003")
a = ap.parse_args()
stats = asyncio.run(run({"gateway": a.gateway, "orders": a.orders, "inventory": a.inventory}, a.minutes * 60,
                        a.scale, a.day_seconds))
print(f"achieved {stats.rate:.1f} req/s")

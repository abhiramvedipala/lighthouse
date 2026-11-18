"""Load generator: the simulator's daily and weekly shape with one day compressed into `day_seconds`.

Per tick, each target gets a Poisson number of requests from rate(t); requests go out through an
httpx AsyncClient with a concurrency cap. Rates are the simulator's peak rates times `scale`, so the
live traffic has the same shape as the offline data at a laptop-sized volume.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
import numpy as np

from lighthouse.sim.config import SimConfig, load_sim_config

DAY_SECONDS = 1200  # 20 minutes per compressed day
TARGETS = {  # (service, endpoint) -> (method, path)
    ("gateway", "GET /products"): ("GET", "/products"),
    ("gateway", "POST /checkout"): ("POST", "/checkout"),
    ("orders", "POST /orders"): ("POST", "/orders"),
    ("orders", "GET /orders/{id}"): ("GET", "/orders/ORD-0000001"),
    ("inventory", "GET /stock/{sku}"): ("GET", "/stock/SKU-00001"),
}


def shape(t_s: float, cfg: SimConfig, day_seconds: float = DAY_SECONDS, start_weekday: int = 0) -> float:
    """Seasonal multiplier at compressed time t_s (daily cosine, peak at cfg.peak_hour, weekend factor)."""
    day_pos = t_s / day_seconds
    hour = (day_pos % 1.0) * 24.0
    daily = 0.2 + 0.8 * (0.5 + 0.5 * np.cos(2 * np.pi * (hour - cfg.peak_hour) / 24.0))
    weekday = (start_weekday + int(day_pos)) % 7
    return float(daily * (cfg.weekend_factor if weekday >= 5 else 1.0))


def rate_per_s(t_s: float, endpoint, cfg: SimConfig, scale: float, day_seconds: float = DAY_SECONDS) -> float:
    ep = next(e for e in cfg.endpoints if (e.service, e.endpoint) == endpoint)
    return ep.peak_rate / 60.0 * scale * shape(t_s, cfg, day_seconds)


@dataclass
class Stats:
    sent: int = 0
    ok: int = 0
    errors: int = 0
    seconds: float = 0.0

    @property
    def rate(self) -> float:
        return self.sent / self.seconds if self.seconds else 0.0


async def run(urls: dict[str, str], duration_s: float, scale: float = 0.25, day_seconds: float = DAY_SECONDS,
              concurrency: int = 64, seed: int = 1, report_every: float = 30.0, log=print, tick: float = 1.0) -> Stats:
    cfg = load_sim_config()
    rng = np.random.default_rng(seed)
    stats = Stats()
    sem = asyncio.Semaphore(concurrency)

    async def fire(client: httpx.AsyncClient, base: str, method: str, path: str):
        async with sem:
            try:
                r = await client.request(method, base + path)
                stats.ok += r.status_code < 500
                stats.errors += r.status_code >= 500
            except httpx.HTTPError:
                stats.errors += 1

    t0 = time.monotonic()
    last_report = t0
    pending: set = set()
    async with httpx.AsyncClient(timeout=10.0) as client:
        while (elapsed := time.monotonic() - t0) < duration_s:
            for key, (method, path) in TARGETS.items():
                n = int(rng.poisson(rate_per_s(elapsed, key, cfg, scale, day_seconds) * tick))
                for _ in range(n):
                    task = asyncio.create_task(fire(client, urls[key[0]], method, path))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
                    stats.sent += 1
            stats.seconds = time.monotonic() - t0
            if time.monotonic() - last_report >= report_every:
                last_report = time.monotonic()
                log(f"t={elapsed:6.0f}s sent={stats.sent} achieved={stats.rate:5.1f} req/s errors={stats.errors}")
            await asyncio.sleep(tick)
        if pending:
            await asyncio.wait(pending, timeout=10)
    stats.seconds = time.monotonic() - t0
    log(f"done: sent={stats.sent} ok={stats.ok} errors={stats.errors} achieved={stats.rate:.1f} req/s "
        f"over {stats.seconds:.0f}s")
    return stats

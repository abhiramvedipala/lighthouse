import asyncio

import httpx
import numpy as np
import pytest
from fastapi import FastAPI

from lighthouse import loadgen
from lighthouse.sim.config import load_sim_config

CFG = load_sim_config()


def test_shape_peaks_at_the_configured_hour_of_the_compressed_day():
    ts = np.linspace(0, loadgen.DAY_SECONDS, 1441)[:-1]
    s = [loadgen.shape(t, CFG) for t in ts]
    assert abs(ts[int(np.argmax(s))] / loadgen.DAY_SECONDS * 24 - CFG.peak_hour) < 0.1
    assert min(s) == pytest.approx(0.2, abs=0.01)


def test_weekend_days_are_sixty_percent_of_weekdays():
    t = 14 / 24 * loadgen.DAY_SECONDS
    assert loadgen.shape(t + 5 * loadgen.DAY_SECONDS, CFG) == pytest.approx(0.6 * loadgen.shape(t, CFG))


def test_rate_scales_with_peak_rate_and_scale():
    t = 14 / 24 * loadgen.DAY_SECONDS
    r = loadgen.rate_per_s(t, ("gateway", "GET /products"), CFG, scale=0.5)
    assert r == pytest.approx(200 / 60 * 0.5)


def test_run_sends_requests_and_reports_the_achieved_rate(monkeypatch):
    app = FastAPI()

    @app.get("/products")
    def products():
        return {}

    @app.post("/checkout")
    def checkout():
        return {}

    real = httpx.AsyncClient
    monkeypatch.setattr(loadgen.httpx, "AsyncClient", lambda **kw: real(transport=httpx.ASGITransport(app=app), **kw))
    logs = []
    urls = {"gateway": "http://t", "orders": "http://t", "inventory": "http://t"}
    stats = asyncio.run(loadgen.run(urls, 3, scale=2.0, day_seconds=20, tick=0.2, report_every=1, log=logs.append))
    assert stats.sent > 5 and stats.ok + stats.errors == stats.sent
    assert 0 < stats.rate < 400 and logs[-1].startswith("done:")

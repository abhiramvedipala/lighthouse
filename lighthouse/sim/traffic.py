"""Seasonal request-rate model and request sampling.

`build_params` makes the clean (fault-free) per-minute, per-endpoint parameters.
Faults edit those arrays in place (see faults.py); `sample_requests` then draws
one row per request from whatever the arrays say.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from lighthouse.sim.config import SimConfig

# err_mode values: which error templates an error request draws from
ERR_BASELINE, ERR_UPSTREAM, ERR_NOVEL = 0, 1, 2


@dataclass
class Params:
    """Per (minute, endpoint) generating parameters. Shape (T, E) unless noted."""

    cfg: SimConfig
    rate: np.ndarray            # expected requests per minute
    mu: np.ndarray              # lognormal location (ln ms)
    sigma: np.ndarray           # shape (E,)
    err: np.ndarray             # probability a request fails
    warn_rate: np.ndarray       # expected WARN lines per request
    err_mode: np.ndarray        # int8, see ERR_* constants
    novel_rate: np.ndarray = field(default=None)   # share of requests failing with the novel error
    deploy: np.ndarray = field(default=None)       # (T, S) bool: deploy window per service


def minute_index(cfg: SimConfig) -> pd.DatetimeIndex:
    return pd.date_range(cfg.start, periods=cfg.minutes, freq="min")


def seasonal_shape(index: pd.DatetimeIndex, cfg: SimConfig) -> np.ndarray:
    """Daily cosine peaking at cfg.peak_hour (floor 0.2 of peak) times a weekend factor."""
    hours = index.hour.to_numpy() + index.minute.to_numpy() / 60.0
    daily = 0.2 + 0.8 * (0.5 + 0.5 * np.cos(2 * np.pi * (hours - cfg.peak_hour) / 24.0))
    weekend = np.where(index.day_of_week.to_numpy() >= 5, cfg.weekend_factor, 1.0)
    return daily * weekend


def build_params(cfg: SimConfig, rng: np.random.Generator) -> Params:
    index = minute_index(cfg)
    T, E = len(index), len(cfg.endpoints)
    shape = seasonal_shape(index, cfg)
    peak = np.array([e.peak_rate for e in cfg.endpoints]) * cfg.rate_scale
    phi = 0.995
    innov_sd = cfg.noise_sd * np.sqrt(1 - phi**2)
    noise = lfilter([1.0], [1.0, -phi], rng.normal(0, innov_sd, size=(T, E)), axis=0)
    rate = shape[:, None] * peak[None, :] * np.exp(noise)
    mu = np.tile(np.log([e.p50_ms for e in cfg.endpoints]), (T, 1))
    sigma = np.array([e.sigma for e in cfg.endpoints])
    return Params(
        cfg=cfg,
        rate=rate,
        mu=mu,
        sigma=sigma,
        err=np.full((T, E), cfg.base_error_rate),
        warn_rate=np.full((T, E), 0.02),
        err_mode=np.zeros((T, E), dtype=np.int8),
        novel_rate=np.zeros((T, E)),
        deploy=np.zeros((T, len(cfg.services)), dtype=bool),
    )


def sample_requests(p: Params, rng: np.random.Generator) -> pd.DataFrame:
    """One row per request: ts (epoch ms), ep (endpoint index), latency_ms, status, novel.

    `novel` marks requests that failed with the novel error template.
    """
    T, E = p.rate.shape
    counts = rng.poisson(p.rate).ravel()
    cell = np.repeat(np.arange(T * E, dtype=np.int32), counts)
    t, e = cell // E, cell % E
    n = len(cell)
    start_ms = int(p.cfg.start.value // 1_000_000)
    ts = start_ms + t.astype(np.int64) * 60_000 + rng.integers(0, 60_000, size=n)
    lat = np.exp(p.mu[t, e] + p.sigma[e] * rng.standard_normal(n)).astype(np.float32)
    u = rng.random(n)
    novel = u < p.novel_rate[t, e]
    failed = novel | (rng.random(n) < p.err[t, e])
    status = np.where(failed, np.where(p.err_mode[t, e] == ERR_UPSTREAM, 503, 500), 200)
    order = np.argsort(ts, kind="stable")
    return pd.DataFrame(
        {
            "ts": ts[order],
            "ep": e[order].astype(np.int8),
            "latency_ms": lat[order],
            "status": status[order].astype(np.int16),
            "novel": novel[order],
        }
    )

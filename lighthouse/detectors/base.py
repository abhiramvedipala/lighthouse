"""Detector interface shared by every detector.

    detector.fit(ds, window)  -> self    # reads only rows of `ds` inside `window` (the train window)
    detector.score(ds)        -> DataFrame, index = minute 0..N-1, one column per service

Scores are causal: the score at minute t may use data up to and including t and nothing later.
Higher means more anomalous. Flags are `score > threshold`, with the threshold chosen on
validation (lighthouse/thresholds.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from lighthouse.data import Dataset

WINDOW = 5  # minutes of smoothing used by every detector's features


class Detector(ABC):
    name = "detector"
    fixed_threshold: float | None = None  # set by detectors with a rule instead of a tuned threshold

    def fit(self, ds: Dataset, window: tuple[int, int]) -> Detector:
        return self

    @abstractmethod
    def score(self, ds: Dataset) -> pd.DataFrame: ...


def service_max(per_key: dict[tuple[str, str], np.ndarray], ds: Dataset) -> pd.DataFrame:
    """Service score = max over its endpoints' scores."""
    out = {}
    for svc in ds.services:
        arrs = [v for (s, _), v in per_key.items() if s == svc]
        out[svc] = np.nanmax(np.vstack(arrs), axis=0)
    return pd.DataFrame(out, index=range(ds.minutes))


def smooth_features(ds: Dataset, key: tuple[str, str], window: int = WINDOW) -> pd.DataFrame:
    """Causal 5-minute features for one endpoint: rate, error rate and log p95 latency.

    rate = mean requests per minute; err = errors / requests over the window; lat = log of the
    rolling median of the per-minute p95 (forward-filled when a minute had no requests).
    """
    s = ds.series(key)
    n = s["request_count"].astype(float)
    errs = s["error_count"].astype(float)
    p95 = s["p95_ms"].ffill().bfill()
    roll = lambda x: x.rolling(window, min_periods=1)  # noqa: E731
    return pd.DataFrame({
        "rate": roll(n).mean(),
        "err": roll(errs).sum() / roll(n).sum().clip(lower=1.0),
        "lat": np.log(roll(p95).median().clip(lower=1.0)),
        "warn": roll(s["warn_error_lines"].astype(float)).sum(),
        "newsig": s["new_sigs_24h"].astype(float),
    })

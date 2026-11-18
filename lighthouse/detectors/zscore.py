"""Rolling z-score: EWMA mean and std per series, flag on |z| above k (k chosen on validation).

Series per endpoint: log request rate, error rate and log p95 (5-minute smoothed). The EWMA adapts
to level shifts, so slow drifts are partly absorbed: the weakness this detector exists to show.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lighthouse.data import Dataset
from lighthouse.detectors.base import Detector, service_max, smooth_features

SPAN = 180  # minutes; alpha = 2 / (span + 1)
SIGNALS = ("rate", "err", "lat")
MIN_STD = 1e-3  # absolute floor so a perfectly constant series cannot divide by zero


class RollingZScore(Detector):
    name = "rolling_zscore"

    def __init__(self, span: int = SPAN):
        self.span = span
        self.std_floor: dict[tuple, float] = {}

    def fit(self, ds: Dataset, window: tuple[int, int]) -> RollingZScore:
        """Learn a per-series floor for the std (half of the train-window std) so quiet periods
        with zero variance, such as an error rate of exactly 0, cannot make one error look infinite."""
        lo, hi = window
        for key in ds.keys:
            f = self._signals(ds, key).iloc[lo:hi]
            mask = ds.train_mask(key[0])[lo:hi]
            for sig in SIGNALS:
                self.std_floor[(key, sig)] = 0.5 * float(f.loc[mask, sig].std())
        return self

    def _signals(self, ds: Dataset, key) -> pd.DataFrame:
        f = smooth_features(ds, key)
        f["rate"] = np.log1p(f["rate"])
        return f[list(SIGNALS)]

    def score(self, ds: Dataset) -> pd.DataFrame:
        alpha = 2.0 / (self.span + 1)
        per_key = {}
        for key in ds.keys:
            f = self._signals(ds, key)
            zs = []
            for sig in SIGNALS:
                x = f[sig]
                mean = x.ewm(alpha=alpha, adjust=False).mean().shift(1)  # past only
                var = ((x - mean) ** 2).ewm(alpha=alpha, adjust=False).mean().shift(1)
                std = np.sqrt(var).clip(lower=max(self.std_floor.get((key, sig), 0.0), MIN_STD))
                zs.append(((x - mean).abs() / std).fillna(0.0).to_numpy())
            per_key[key] = np.max(zs, axis=0)
        return service_max(per_key, ds)

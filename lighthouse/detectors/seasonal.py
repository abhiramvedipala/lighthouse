"""Seasonal baseline: median and MAD per (weekday-or-weekend, 5-minute slot of the day), from train.

For each endpoint and each of three 5-minute smoothed signals (log request rate, error rate, log p95)
the train window gives a median and a MAD per slot (a slot also pools its two neighbours, so a
weekend slot has about 30 samples instead of 10). Score = robust z of the residual
(x - median) / (1.4826 * MAD, floored), taken in the harmful direction only (a rate drop, an
error rate rise, a latency rise) and divided by that series' train 99.9th percentile so the three
signals are comparable. A planned traffic surge is therefore not an alarm by itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lighthouse.data import Dataset
from lighthouse.detectors.base import Detector, service_max, smooth_features

SLOTS = 288          # 5-minute slots per day
SIGNALS = ("rate", "err", "lat")
DIRECTION = {"rate": -1.0, "err": 1.0, "lat": 1.0}  # sign of the harmful deviation
MAD_SCALE = 1.4826


def slot_ids(ds: Dataset) -> np.ndarray:
    """Slot index (0..575) for each minute of the dataset: weekend flag * 288 + minute-of-day // 5."""
    ts = pd.date_range(ds.start, periods=ds.minutes, freq="min")
    weekend = (ts.day_of_week >= 5).astype(int)
    return (weekend * SLOTS + (ts.hour * 60 + ts.minute) // 5).to_numpy()


def signals(ds: Dataset, key) -> pd.DataFrame:
    f = smooth_features(ds, key)
    f["rate"] = np.log1p(f["rate"])
    return f[list(SIGNALS)]


class SeasonalBaseline(Detector):
    name = "seasonal_baseline"

    def __init__(self, pool: int = 1):
        self.pool = pool
        self.median: dict[tuple, np.ndarray] = {}
        self.scale: dict[tuple, np.ndarray] = {}
        self.norm: dict[tuple, float] = {}

    def fit(self, ds: Dataset, window: tuple[int, int]) -> SeasonalBaseline:
        lo, hi = window
        sid = slot_ids(ds)[lo:hi]
        for key in ds.keys:
            mask = ds.train_mask(key[0])[lo:hi]
            sig = signals(ds, key).iloc[lo:hi]
            for name in SIGNALS:
                x = sig[name].to_numpy()[mask]
                s = sid[mask]
                med = np.full(2 * SLOTS, np.nan)
                mad = np.full(2 * SLOTS, np.nan)
                for day_type in (0, 1):
                    for slot in range(SLOTS):
                        near = [(slot + d) % SLOTS + day_type * SLOTS for d in range(-self.pool, self.pool + 1)]
                        vals = x[np.isin(s, near)]
                        if len(vals):
                            med[day_type * SLOTS + slot] = np.median(vals)
                            mad[day_type * SLOTS + slot] = np.median(np.abs(vals - np.median(vals)))
                # slots never seen (for example a weekend slot with every sample masked): use the day-type median
                for day_type in (0, 1):
                    sl = slice(day_type * SLOTS, (day_type + 1) * SLOTS)
                    fallback = np.nanmedian(med[sl]) if np.isfinite(med[sl]).any() else np.nanmedian(med)
                    med[sl] = np.where(np.isfinite(med[sl]), med[sl], fallback)
                    madfb = np.nanmedian(mad[sl]) if np.isfinite(mad[sl]).any() else 0.0
                    mad[sl] = np.where(np.isfinite(mad[sl]), mad[sl], madfb)
                resid = x - med[s]
                floor = 0.5 * float(np.std(resid)) + 1e-6  # keeps a MAD of 0 (error rate) from giving infinite z
                self.median[(key, name)] = med
                self.scale[(key, name)] = np.maximum(MAD_SCALE * mad, floor)
                z = DIRECTION[name] * resid / self.scale[(key, name)][s]
                # per-series normaliser: the 99.9th percentile of the harmful-direction z on train, so a
                # heavy-tailed signal (error rate) does not drown out a well-behaved one (rate)
                self.norm[(key, name)] = max(float(np.quantile(np.clip(z, 0, None), 0.999)), 1.0)
        return self

    def residuals(self, ds: Dataset, key) -> pd.DataFrame:
        """Signed robust z of each signal at every minute (positive = harmful direction)."""
        sid = slot_ids(ds)
        sig = signals(ds, key)
        out = {}
        for name in SIGNALS:
            z = (sig[name].to_numpy() - self.median[(key, name)][sid]) / self.scale[(key, name)][sid]
            out[name] = DIRECTION[name] * z
        return pd.DataFrame(out)

    def score(self, ds: Dataset) -> pd.DataFrame:
        """Max over signals of the harmful-direction z divided by its train 99.9th percentile."""
        per_key = {}
        for key in ds.keys:
            z = self.residuals(ds, key).clip(lower=0)
            for name in SIGNALS:
                z[name] = z[name] / self.norm[(key, name)]
            per_key[key] = z.max(axis=1).to_numpy()
        return service_max(per_key, ds)

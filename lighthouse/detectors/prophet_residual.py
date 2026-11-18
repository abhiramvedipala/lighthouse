"""Prophet residual detector: per series, daily + weekly seasonality on 5-minute resamples.

One Prophet model per endpoint and signal (log rate, error rate, log p95), fitted on the clean
train bins. A bin's score is the harmful-direction residual divided by the predicted interval
width, then divided by that series' train 99.9th percentile so the signals are comparable (the
same normaliser as the seasonal baseline). A minute takes the score of the latest completed bin,
so scores are causal. Fit time per series is logged; `resample` can be raised to 15 minutes if the
20-minute budget for the offline train+evaluate run is at risk.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from lighthouse.data import Dataset
from lighthouse.detectors.base import Detector, service_max, smooth_features

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

SEED = 20261112
SIGNALS = ("rate", "err", "lat")
DIRECTION = {"rate": -1.0, "err": 1.0, "lat": 1.0}


class ProphetResidual(Detector):
    name = "prophet_residual"

    def __init__(self, resample: int = 5, uncertainty_samples: int = 200, interval_width: float = 0.8,
                 seed: int = SEED):
        self.resample, self.uncertainty_samples = resample, uncertainty_samples
        self.interval_width, self.seed = interval_width, seed
        self.models: dict = {}
        self.norm: dict = {}
        self.fit_seconds: dict = {}
        self.train_window: tuple[int, int] = (0, 0)

    def _bins(self, ds: Dataset, key) -> tuple[pd.DataFrame, np.ndarray]:
        """Signals at the end of each completed bin, and the minute index each bin ends on."""
        f = smooth_features(ds, key, window=self.resample)
        f["rate"] = np.log1p(f["rate"])
        idx = np.arange(self.resample - 1, ds.minutes, self.resample)
        sig = f.iloc[idx][list(SIGNALS)].reset_index(drop=True)
        sig.insert(0, "ds", ds.start + pd.to_timedelta(idx, unit="min"))
        return sig, idx

    def fit(self, ds: Dataset, window: tuple[int, int]) -> ProphetResidual:
        from prophet import Prophet

        for name in ("cmdstanpy", "prophet"):  # prophet re-enables INFO output on import
            logging.getLogger(name).setLevel(logging.WARNING)
        self.train_window = window
        lo, hi = window
        for key in ds.keys:
            sig, idx = self._bins(ds, key)
            mask = ds.train_mask(key[0])[idx] & (idx >= lo) & (idx < hi)
            for name in SIGNALS:
                df = sig[["ds", name]].rename(columns={name: "y"}).copy()
                df.loc[~mask, "y"] = np.nan  # outside train or inside a fault: not used for fitting
                df = df[(idx >= lo) & (idx < hi)]
                np.random.seed(self.seed)
                t0 = time.perf_counter()
                m = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False,
                            uncertainty_samples=self.uncertainty_samples, interval_width=self.interval_width)
                m.fit(df.dropna())
                self.fit_seconds[(key, name)] = time.perf_counter() - t0
                self.models[(key, name)] = m
        return self

    def _z(self, ds: Dataset, key, name: str) -> tuple[np.ndarray, np.ndarray]:
        """Signed harmful-direction residual / interval width at each bin end, and the bin end minutes."""
        sig, idx = self._bins(ds, key)
        np.random.seed(self.seed)
        fc = self.models[(key, name)].predict(sig[["ds"]])
        width = (fc["yhat_upper"] - fc["yhat_lower"]).to_numpy().clip(min=1e-6)
        resid = DIRECTION[name] * (sig[name].to_numpy() - fc["yhat"].to_numpy())
        return resid / width, idx

    def score(self, ds: Dataset) -> pd.DataFrame:
        lo, hi = self.train_window
        per_key = {}
        for key in ds.keys:
            best = np.zeros(ds.minutes)
            for name in SIGNALS:
                z, idx = self._z(ds, key, name)
                z = np.clip(z, 0, None)
                if (key, name) not in self.norm:
                    in_train = (idx >= lo) & (idx < hi)
                    self.norm[(key, name)] = max(float(np.quantile(z[in_train], 0.999)), 1e-3)
                z = z / self.norm[(key, name)]
                minute_z = np.zeros(ds.minutes)
                minute_z[idx] = z
                # a minute inherits the latest completed bin; the first partial bin scores 0
                filled = pd.Series(np.where(np.isin(np.arange(ds.minutes), idx), minute_z, np.nan)).ffill().fillna(0.0)
                best = np.maximum(best, filled.to_numpy())
            per_key[key] = best
        return service_max(per_key, ds)

"""Isolation Forest per service on a multivariate feature vector.

Per endpoint of the service (concatenated into one vector): 5-minute log rate, error rate, log p95,
log p99, WARN/ERROR line count, new-signature features, each metric also as a residual from the
seasonal baseline (fitted on the same train window), plus 5-minute deltas of rate, error rate and
latency. `n_estimators=200`, contamination left at "auto", threshold picked on validation.

Switches exist for the ablations: residual features on/off, template (log) features on/off, and
clean versus contaminated training minutes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from lighthouse.data import Dataset
from lighthouse.detectors.base import Detector, smooth_features
from lighthouse.detectors.seasonal import SeasonalBaseline

SEED = 20261112
WARMUP_MIN = 1440      # new_sigs_24h needs a day of history; day 1 is cold start
Z_CLIP = 30.0


class IsolationForestDetector(Detector):
    name = "isolation_forest"

    def __init__(self, residuals: bool = True, templates: bool = True, clean_train: bool = True,
                 n_estimators: int = 200, seed: int = SEED, raw: bool = True, per_endpoint: bool = False,
                 deltas: bool = True):
        self.use_residuals, self.use_templates, self.clean_train = residuals, templates, clean_train
        self.raw, self.per_endpoint, self.deltas = raw, per_endpoint, deltas
        self.n_estimators, self.seed = n_estimators, seed
        self.seasonal: SeasonalBaseline | None = None
        self.models: dict[str, IsolationForest] = {}
        self.names: list[str] = []

    # ---- features --------------------------------------------------------------------------------
    def endpoint_features(self, ds: Dataset, key) -> pd.DataFrame:
        f = smooth_features(ds, key)
        s = ds.series(key)
        out = pd.DataFrame({
            "rate": np.log1p(f["rate"]),
            "err": f["err"],
            "lat": f["lat"],
            "lat99": np.log(s["p99_ms"].ffill().bfill().rolling(5, min_periods=1).median().clip(lower=1.0)),
        })
        if self.use_templates:
            out["warn"] = np.log1p(f["warn"])
            out["newsig24"] = f["newsig"]
            out["newsig5"] = (f["newsig"] - f["newsig"].shift(5)).clip(lower=0).fillna(0.0)
        if self.use_residuals:
            z = self.seasonal.residuals(ds, key).clip(-Z_CLIP, Z_CLIP)
            out["z_rate"], out["z_err"], out["z_lat"] = z["rate"], z["err"], z["lat"]
        for c in ("rate", "err", "lat") if self.deltas else ():
            out[f"d_{c}"] = (out[c] - out[c].shift(5)).fillna(0.0)
        if not self.raw:  # residual-only view: drop the seasonal raw levels, keep deltas and template counts
            out = out.drop(columns=[c for c in ("rate", "err", "lat", "lat99") if c in out])
        return out

    def units(self, ds: Dataset) -> dict:
        """Model units: one per service (concatenated endpoint features) or one per endpoint."""
        if self.per_endpoint:
            return {key: [key] for key in ds.keys}
        return {svc: [k for k in ds.keys if k[0] == svc] for svc in ds.services}

    def features(self, ds: Dataset, keys: list) -> pd.DataFrame:
        parts = []
        for key in keys:
            f = self.endpoint_features(ds, key)
            f.columns = [f"{key[1]}:{c}" for c in f.columns]
            parts.append(f)
        return pd.concat(parts, axis=1)

    # ---- fit / score -----------------------------------------------------------------------------
    def fit(self, ds: Dataset, window: tuple[int, int]) -> IsolationForestDetector:
        lo, hi = window
        self.seasonal = SeasonalBaseline().fit(ds, window)
        for unit, keys in self.units(ds).items():
            X = self.features(ds, keys)
            self.names = list(X.columns)
            svc = keys[0][0]
            use = ds.train_mask(svc).copy() if self.clean_train else np.zeros(ds.minutes, dtype=bool)
            if not self.clean_train:
                use[lo:hi] = True
            use[:min(WARMUP_MIN, hi)] = False
            use[hi:] = False
            m = IsolationForest(n_estimators=self.n_estimators, contamination="auto", random_state=self.seed, n_jobs=4)
            self.models[unit] = m.fit(X.to_numpy(dtype=np.float32)[use])
        return self

    def score(self, ds: Dataset) -> pd.DataFrame:
        per_service: dict[str, list] = {}
        for unit, keys in self.units(ds).items():
            X = self.features(ds, keys).to_numpy(dtype=np.float32)
            per_service.setdefault(keys[0][0], []).append(-self.models[unit].score_samples(X))
        return pd.DataFrame({svc: np.max(v, axis=0) for svc, v in per_service.items()}, index=range(ds.minutes))

    # ---- explanation -----------------------------------------------------------------------------
    def permutation_importance(self, ds: Dataset, window: tuple[int, int], n_repeats: int = 3, seed: int = 0):
        """AUC drop on `window` (validation) when one feature, across all endpoints, is shuffled.

        AUC is minute level: a service-minute is positive inside a real incident that touches the
        service. A bigger drop means the model leans on that feature to separate incident minutes.
        """
        from sklearn.metrics import roc_auc_score

        lo, hi = window
        rng = np.random.default_rng(seed)
        drops: dict[str, list[float]] = {}
        for unit, keys in self.units(ds).items():
            svc = keys[0][0]
            y = np.zeros(hi - lo, dtype=bool)
            for inc in ds.incidents_in((0, ds.minutes), benign=False):
                if svc in inc.services:
                    y[max(inc.start, lo) - lo:max(min(inc.end, hi) - lo, 0)] = True
            if y.sum() == 0 or y.all():
                continue
            X = self.features(ds, keys).to_numpy(dtype=np.float32)[lo:hi]
            names = [c.split(":", 1)[1] for c in self.features(ds, keys).columns]
            base = roc_auc_score(y, -self.models[unit].score_samples(X))
            for feat in dict.fromkeys(names):
                cols = [i for i, n in enumerate(names) if n == feat]
                aucs = []
                for _ in range(n_repeats):
                    Xp = X.copy()
                    for c in cols:
                        Xp[:, c] = rng.permutation(Xp[:, c])
                    aucs.append(roc_auc_score(y, -self.models[unit].score_samples(Xp)))
                drops.setdefault(feat, []).append(base - float(np.mean(aucs)))
        return pd.DataFrame({"feature": list(drops), "auc_drop": [float(np.mean(v)) for v in drops.values()]}) \
            .sort_values("auc_drop", ascending=False).reset_index(drop=True)

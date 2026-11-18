"""Live windows and detectors for the streaming consumer.

The live stack runs on a compressed clock (one day in 20 minutes), so the offline minute-level
detectors cannot be reused directly. This module keeps their logic on 10-second windows: a window
is the unit, and a compressed day has `day_seconds / WINDOW_S` seasonal slots.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

WINDOW_S = 10
SMOOTH = 3          # windows of trailing smoothing (the live analogue of the 5-minute features)
SUSTAIN = 6         # windows the static condition must hold (60 s live, 5 minutes offline)
DIRECTION = {"rate": -1.0, "err": 1.0, "lat": 1.0}
SIGNALS = tuple(DIRECTION)
Key = tuple[str, str]


@dataclass
class Acc:
    n: int = 0
    errs: int = 0
    lat: list = field(default_factory=list)
    warn: int = 0
    sigs: set = field(default_factory=set)
    new_sigs: int = 0


class Windower:
    """Accumulate spans and logs into (window index, service, endpoint) cells; release old ones."""

    def __init__(self, grace_windows: int = 1):
        self.cells: dict[tuple, Acc] = defaultdict(Acc)
        self.grace = grace_windows

    @staticmethod
    def index(ts_ms: int) -> int:
        return ts_ms // (WINDOW_S * 1000)

    def add_span(self, s) -> None:
        c = self.cells[(self.index(s.end_ms), s.service, s.endpoint)]
        c.n += 1
        c.errs += int(s.error)
        c.lat.append(s.duration_ms)

    def add_log(self, rec, sig_key: str | None, is_new: bool) -> None:
        c = self.cells[(self.index(rec.ts_ms), rec.service, rec.endpoint)]
        c.warn += rec.level in ("WARN", "ERROR")
        if sig_key:
            c.sigs.add(sig_key)
            c.new_sigs += int(is_new)

    def pop_ready(self, now_ms: int) -> list[dict]:
        """Rows for windows that ended at least `grace` windows ago."""
        limit = self.index(now_ms) - self.grace
        rows = []
        for k in sorted(k for k in self.cells if k[0] < limit):
            c = self.cells.pop(k)
            rows.append({"window": k[0], "service": k[1], "endpoint": k[2], "n": c.n, "errs": c.errs,
                         "p95": float(np.percentile(c.lat, 95)) if c.lat else np.nan, "warn": c.warn,
                         "new_sigs": c.new_sigs})
        return rows


def signals(df: pd.DataFrame) -> pd.DataFrame:
    """Smoothed rate, error rate, log p95 for one endpoint's window rows (sorted by window)."""
    r = lambda x: x.rolling(SMOOTH, min_periods=1)  # noqa: E731
    return pd.DataFrame({
        "rate": np.log1p(r(df["n"].astype(float)).mean()),
        "err": r(df["errs"].astype(float)).sum() / r(df["n"].astype(float)).sum().clip(lower=1.0),
        "lat": np.log(r(df["p95"].ffill().bfill()).median().clip(lower=1.0)),
    }, index=df.index)


class LiveSeasonal:
    """Median/MAD per window-of-compressed-day slot, harmful-direction robust z, normalised."""

    def __init__(self, day_seconds: float = 1200, pool: int = 1):
        self.slots = int(day_seconds // WINDOW_S)
        self.pool = pool
        self.med: dict = {}
        self.scale: dict = {}
        self.norm: dict = {}

    def slot(self, window) -> np.ndarray:
        return np.asarray(window) % self.slots

    def fit(self, hist: pd.DataFrame) -> LiveSeasonal:
        for key, g in hist.groupby(["service", "endpoint"]):
            g = g.sort_values("window")
            sig, sid = signals(g), self.slot(g["window"])
            for name in SIGNALS:
                x = sig[name].to_numpy()
                med, mad = np.full(self.slots, np.nan), np.full(self.slots, np.nan)
                for s in range(self.slots):
                    near = [(s + d) % self.slots for d in range(-self.pool, self.pool + 1)]
                    v = x[np.isin(sid, near)]
                    if len(v):
                        med[s], mad[s] = np.median(v), np.median(np.abs(v - np.median(v)))
                med = np.where(np.isfinite(med), med, np.nanmedian(med))
                mad = np.where(np.isfinite(mad), mad, np.nanmedian(mad))
                floor = 0.5 * float(np.std(x - med[sid])) + 1e-6
                scale = np.maximum(1.4826 * mad, floor)
                z = DIRECTION[name] * (x - med[sid]) / scale[sid]
                self.med[(key, name)], self.scale[(key, name)] = med, scale
                self.norm[(key, name)] = max(float(np.quantile(np.clip(z, 0, None), 0.999)), 1.0)
        return self

    def z(self, key: Key, window: np.ndarray, sig: pd.DataFrame) -> pd.DataFrame:
        sid = self.slot(window)
        return pd.DataFrame({n: DIRECTION[n] * (sig[n].to_numpy() - self.med[(key, n)][sid]) / self.scale[(key, n)][sid]
                             for n in SIGNALS}, index=sig.index)

    def score(self, key: Key, hist: pd.DataFrame) -> float:
        """Score of the newest window in `hist` (rows of one endpoint, sorted)."""
        sig = signals(hist)
        z = self.z(key, hist["window"].to_numpy()[-1:], sig.tail(1))
        return float(max(max(z[n].iloc[-1], 0.0) / self.norm[(key, n)] for n in SIGNALS))


def static_score(hist: pd.DataFrame, slo_p95: float) -> float:
    """Strictest of the last SUSTAIN windows of max(err/5%, p95/(2 x SLO)); >= 1 means the alert fires."""
    tail = hist.tail(SUSTAIN)
    if len(tail) < SUSTAIN:
        return 0.0
    err = (tail["errs"] / tail["n"].clip(lower=1)) / 0.05
    lat = (tail["p95"] / (2 * slo_p95)).fillna(0.0)
    return float(np.maximum(err, lat).min())


class LiveForest:
    """Per service Isolation Forest on seasonal residuals of its endpoints plus new-signature counts."""

    def __init__(self, seasonal: LiveSeasonal, seed: int = 20261112):
        self.seasonal, self.seed = seasonal, seed
        self.models: dict = {}
        self.threshold: dict = {}

    def matrix(self, hist: pd.DataFrame, service: str) -> pd.DataFrame:
        cols = {}
        for (svc, ep), g in hist.groupby(["service", "endpoint"]):
            if svc != service:
                continue
            g = g.sort_values("window")
            z = self.seasonal.z((svc, ep), g["window"].to_numpy(), signals(g)).clip(-30, 30)
            for n in SIGNALS:
                cols[f"{ep}:z_{n}"] = pd.Series(z[n].to_numpy(), index=g["window"].to_numpy())
            cols[f"{ep}:new"] = pd.Series(g["new_sigs"].to_numpy(dtype=float), index=g["window"].to_numpy())
        return pd.DataFrame(cols).sort_index().fillna(0.0)

    def fit(self, hist: pd.DataFrame) -> LiveForest:
        for svc in hist["service"].unique():
            X = self.matrix(hist, svc)
            m = IsolationForest(n_estimators=200, contamination="auto", random_state=self.seed, n_jobs=2)
            self.models[svc] = (m.fit(X.to_numpy(np.float32)), list(X.columns))
            self.threshold[svc] = float(np.quantile(-self.models[svc][0].score_samples(X.to_numpy(np.float32)), 0.999))
        return self

    def score(self, hist: pd.DataFrame, service: str) -> float:
        model, cols = self.models[service]
        X = self.matrix(hist, service).reindex(columns=cols, fill_value=0.0)
        return float(-model.score_samples(X.to_numpy(np.float32)[-1:])[0])


class Tail:
    """Last few window rows per endpoint so each new window can be scored without rebuilding history."""

    def __init__(self, keep: int = 24):
        self.keep = keep
        self.rows: dict[Key, deque] = defaultdict(lambda: deque(maxlen=keep))

    def add(self, row: dict) -> pd.DataFrame:
        q = self.rows[(row["service"], row["endpoint"])]
        q.append(row)
        return pd.DataFrame(list(q)).reset_index(drop=True)

"""The alert most teams already have: error rate above 5 percent or p95 above 2x SLO, for 5 minutes.

This is the baseline and the reference for lead time. It is deliberately not tuned: the rule is
fixed, so the score is just the strictest of the last five minutes and the flag threshold is 1.0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lighthouse.data import Dataset
from lighthouse.detectors.base import Detector, service_max

ERROR_RATE_LIMIT = 0.05
P95_SLO_MULTIPLE = 2.0
SUSTAIN_MIN = 5


class StaticThreshold(Detector):
    name = "static_threshold"
    fixed_threshold = 1.0

    def score(self, ds: Dataset) -> pd.DataFrame:
        per_key = {}
        for key in ds.keys:
            s = ds.series(key)
            slo = ds.slo[key]["p95_ms"]
            err_ratio = (s["error_rate"] / ERROR_RATE_LIMIT).fillna(0.0)
            lat_ratio = (s["p95_ms"] / (P95_SLO_MULTIPLE * slo)).fillna(0.0)  # no requests: no latency evidence
            cond = np.maximum(err_ratio, lat_ratio)
            per_key[key] = cond.rolling(SUSTAIN_MIN, min_periods=SUSTAIN_MIN).min().fillna(0.0).to_numpy()
        return service_max(per_key, ds)

"""Threshold selection on the validation window only.

Maximise incident-level F1 subject to at most `max_fa` false alarms per service per day. The
function takes validation scores and validation incidents and nothing else, so it cannot see the
test window by construction (tests/test_leakage.py checks this).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from lighthouse.evaluate import Incident, evaluate

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "results" / "thresholds.json"


def flags_from_scores(scores: pd.DataFrame, threshold: float) -> dict[str, np.ndarray]:
    return {svc: (scores[svc].to_numpy() > threshold) for svc in scores.columns}


def select_threshold(
    scores: pd.DataFrame,
    incidents: list[Incident],
    window: tuple[int, int],
    max_fa: float = 1.0,
    n_candidates: int = 120,
) -> dict:
    """Return {threshold, f1, precision, recall, fa_per_service_day, feasible} chosen on `window`."""
    lo, hi = window
    vals = np.concatenate([scores[c].to_numpy()[lo:hi] for c in scores.columns])
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return {"threshold": float("inf"), "f1": 0.0, "precision": float("nan"), "recall": 0.0,
                "fa_per_service_day": 0.0, "feasible": False}
    qs = np.unique(np.quantile(vals, np.linspace(0.90, 0.9999, n_candidates)))
    best, fallback = None, None
    for thr in qs:
        r = evaluate(flags_from_scores(scores, float(thr)), incidents, window, n_services=scores.shape[1])
        row = {"threshold": float(thr), "f1": r.f1, "precision": r.precision, "recall": r.recall,
               "fa_per_service_day": r.false_alarms_per_service_day}
        if fallback is None or row["fa_per_service_day"] < fallback["fa_per_service_day"]:
            fallback = row
        if row["fa_per_service_day"] <= max_fa and (best is None or row["f1"] >= best["f1"]):
            best = row  # ties go to the higher threshold (quantiles ascend): fewer false alarms
    if best is None:
        return {**fallback, "feasible": False}
    return {**best, "feasible": True}


def save_thresholds(table: dict, path: Path = THRESHOLDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=1, sort_keys=True))

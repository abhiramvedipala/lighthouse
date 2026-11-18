"""Dataset: the aggregate table, labels, time-based splits and per-series arrays.

Splits are by time only: days 1-7 train, 8-10 validation, 11-14 test (same proportions for any
window length). Detectors are fitted on the train window and threshold-selected on the
validation window; the test window is scored once at the end.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from lighthouse.aggregate import FIXTURE_DIR, SIM_DIR, aggregate_dir
from lighthouse.evaluate import Incident, incidents_from_labels
from lighthouse.sim.config import load_slo

TRAIN_FRAC, VAL_FRAC = 7 / 14, 3 / 14
PAD_BEFORE, PAD_AFTER = 10, 30  # minutes excluded around a fault when fitting


@dataclass
class Dataset:
    agg: pd.DataFrame
    start: pd.Timestamp
    minutes: int
    labels: dict
    slo: dict
    incidents: list[Incident] = field(default_factory=list)
    fracs: tuple = (TRAIN_FRAC, VAL_FRAC)   # train and validation shares of the window
    _series: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.agg = self.agg.sort_values(["service", "endpoint", "ts"]).reset_index(drop=True)
        self.incidents = incidents_from_labels(self.labels, self.start)

    @property
    def keys(self) -> list[tuple[str, str]]:
        return list(dict.fromkeys(zip(self.agg["service"], self.agg["endpoint"], strict=True)))

    @property
    def services(self) -> list[str]:
        return list(dict.fromkeys(self.agg["service"]))

    @property
    def splits(self) -> dict[str, tuple[int, int]]:
        a = int(self.minutes * self.fracs[0])
        b = a + int(self.minutes * self.fracs[1])
        return {"train": (0, a), "val": (a, b), "test": (b, self.minutes)}

    def series(self, key: tuple[str, str]) -> pd.DataFrame:
        """Raw per-minute columns for one endpoint, indexed 0..minutes-1."""
        if key not in self._series:
            g = self.agg[(self.agg["service"] == key[0]) & (self.agg["endpoint"] == key[1])]
            self._series[key] = g.reset_index(drop=True).drop(columns=["service", "endpoint"])
        return self._series[key]

    def incidents_in(self, window: tuple[int, int], benign: bool | None = None) -> list[Incident]:
        lo, hi = window
        return [i for i in self.incidents if lo <= i.start < hi and (benign is None or i.benign == benign)]

    def train_mask(self, service: str) -> np.ndarray:
        """True for minutes usable for fitting a service's model: inside the train window and not
        within a fault (with padding) that touches the service. Benign events stay in."""
        lo, hi = self.splits["train"]
        mask = np.zeros(self.minutes, dtype=bool)
        mask[lo:hi] = True
        for inc in self.incidents:
            if not inc.benign and service in inc.services:
                mask[max(0, inc.start - PAD_BEFORE):inc.end + PAD_AFTER] = False
        return mask


def load_dataset(source: str = "sim", directory: Path | None = None, rebuild: bool = False) -> Dataset:
    src = directory or (SIM_DIR if source == "sim" else FIXTURE_DIR)
    cache = (src / "aggregates.parquet") if source == "sim" else (SIM_DIR.parent / "fixture_aggregates.parquet")
    if rebuild or not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        aggregate_dir(src).to_parquet(cache, index=False)
    agg = pd.read_parquet(cache)
    labels = json.loads((src / "labels.json").read_text())
    start = pd.Timestamp(agg["ts"].min())
    minutes = int(agg["ts"].nunique())
    return Dataset(agg, start, minutes, labels, load_slo())

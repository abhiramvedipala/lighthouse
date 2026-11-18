"""Simulator and SLO configuration loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@dataclass(frozen=True)
class Endpoint:
    service: str
    endpoint: str
    peak_rate: float
    p50_ms: float
    sigma: float


@dataclass(frozen=True)
class SimConfig:
    seed: int
    start: pd.Timestamp
    days: int
    rate_scale: float
    info_sample: int
    base_error_rate: float
    weekend_factor: float
    peak_hour: float
    noise_sd: float
    endpoints: tuple[Endpoint, ...]

    @property
    def minutes(self) -> int:
        return self.days * 1440

    @property
    def services(self) -> list[str]:
        return list(dict.fromkeys(e.service for e in self.endpoints))

    def endpoint_index(self, service: str, endpoint: str) -> int:
        for i, e in enumerate(self.endpoints):
            if e.service == service and e.endpoint == endpoint:
                return i
        raise KeyError((service, endpoint))

    def child_rngs(self, n: int = 3) -> list[np.random.Generator]:
        """Independent streams so changing one component never shifts another."""
        return [np.random.default_rng(s) for s in np.random.SeedSequence(self.seed).spawn(n)]


def load_sim_config(path: Path | str | None = None, **overrides) -> SimConfig:
    raw = yaml.safe_load(Path(path or CONFIG_DIR / "sim.yaml").read_text())
    raw.update(overrides)
    eps = tuple(Endpoint(**e) for e in raw.pop("endpoints"))
    raw["start"] = pd.Timestamp(raw["start"])
    return SimConfig(endpoints=eps, **raw)


def load_slo(path: Path | str | None = None) -> dict[tuple[str, str], dict]:
    raw = yaml.safe_load(Path(path or CONFIG_DIR / "slo.yaml").read_text())
    return {(svc, ep): v for svc, eps in raw.items() for ep, v in eps.items()}

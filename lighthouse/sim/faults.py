"""Labeled fault injection and benign events.

`inject` schedules faults (stratified across the whole window so every split
sees every type), edits the Params arrays in place, and returns the labels
that evaluation scores against.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from lighthouse.sim.traffic import ERR_UPSTREAM, Params

FAULT_TYPES = (
    "latency_spike", "error_burst", "dependency_outage", "latency_drift", "traffic_drop", "novel_error",
)
BENIGN_TYPES = ("traffic_surge", "deploy")

# faults per type over 14 days (about 40) and benign events (6)
FAULT_COUNTS = {
    "latency_spike": 8, "error_burst": 8, "dependency_outage": 4,
    "latency_drift": 6, "traffic_drop": 6, "novel_error": 8,
}
BENIGN_COUNTS = {"traffic_surge": 4, "deploy": 2}
DURATION_MIN = {  # (low, high) minutes
    "latency_spike": (5, 30), "error_burst": (5, 30), "dependency_outage": (5, 20),
    "latency_drift": (120, 360), "traffic_drop": (10, 60), "novel_error": (30, 120),
    "traffic_surge": (60, 60), "deploy": (3, 6),
}
GAP_MIN = 60  # minimum quiet time between events touching the same service


@dataclass
class Event:
    id: str
    type: str
    service: str
    endpoint: str
    start_min: int          # minute index into the window
    end_min: int            # exclusive
    severity: float
    benign: bool = False
    affected: list = field(default_factory=list)  # [{service, endpoint, start_min}] incl. cascades

    def to_label(self, cfg) -> dict:
        d = asdict(self)
        d["start"] = str(cfg.start + np.timedelta64(self.start_min, "m"))
        d["end"] = str(cfg.start + np.timedelta64(self.end_min, "m"))
        for a in d["affected"]:
            a["start"] = str(cfg.start + np.timedelta64(a["start_min"], "m"))
        return d


def _scaled_counts(base: dict, days: int, floor: int) -> dict:
    if days >= 14:
        return dict(base)
    return {k: max(floor, round(v * days / 14)) for k, v in base.items()}


def _services_touched(cfg, ev_type: str, service: str) -> set:
    if ev_type == "dependency_outage":
        return {"inventory", "orders", "gateway"}
    if ev_type == "traffic_surge":
        return set(cfg.services)
    return {service}


def schedule(cfg, rng) -> list[Event]:
    """Stratified random placement: type i of n events gets one of n equal slices of the window."""
    T = cfg.minutes
    margin = 120
    busy: dict[str, list[tuple[int, int]]] = {s: [] for s in cfg.services}
    events: list[Event] = []
    counts = [(t, n, False) for t, n in _scaled_counts(FAULT_COUNTS, cfg.days, 2).items()]
    counts += [(t, n, True) for t, n in _scaled_counts(BENIGN_COUNTS, cfg.days, 1).items()]
    for etype, n, benign in counts:
        lo_d, hi_d = DURATION_MIN[etype]
        for i in range(n):
            lo = margin + (T - 2 * margin) * i // n
            hi = margin + (T - 2 * margin) * (i + 1) // n
            for _ in range(200):
                dur = int(rng.integers(lo_d, hi_d + 1))
                start = int(rng.integers(lo, max(lo + 1, hi - dur)))
                if etype == "dependency_outage":
                    service, endpoint = "inventory", "GET /stock/{sku}"
                else:
                    e = cfg.endpoints[int(rng.integers(0, len(cfg.endpoints)))]
                    service, endpoint = e.service, e.endpoint
                touched = _services_touched(cfg, etype, service)
                end = start + dur
                if any(a < end + GAP_MIN and start < b + GAP_MIN for s in touched for a, b in busy[s]):
                    continue
                for s in touched:
                    busy[s].append((start, end))
                events.append(Event(f"{'b' if benign else 'f'}{len(events):02d}-{etype}", etype, service,
                                    endpoint, start, end, 0.0, benign))
                break
    events.sort(key=lambda e: e.start_min)
    for k, ev in enumerate(events):
        ev.id = f"{'b' if ev.benign else 'f'}{k:02d}-{ev.type}"
    return events


def _apply(p: Params, ev: Event, rng) -> None:
    cfg = p.cfg
    s, e = ev.start_min, ev.end_min
    ep = cfg.endpoint_index(ev.service, ev.endpoint)
    n = e - s
    ev.affected = [{"service": ev.service, "endpoint": ev.endpoint, "start_min": s}]
    if ev.type == "latency_spike":
        ev.severity = float(rng.uniform(3, 10))
        p.mu[s:e, ep] += np.log(ev.severity)
        p.warn_rate[s:e, ep] *= 4
    elif ev.type == "error_burst":
        ev.severity = float(rng.uniform(0.05, 0.40))
        p.err[s:e, ep] = np.maximum(p.err[s:e, ep], ev.severity)
        p.warn_rate[s:e, ep] *= 2
    elif ev.type == "dependency_outage":
        ev.severity = 0.95
        inv = cfg.endpoint_index("inventory", "GET /stock/{sku}")
        p.err[s:e, inv] = ev.severity
        p.err_mode[s:e, inv] = ERR_UPSTREAM
        lag_o = int(rng.integers(1, 3))
        lag_g = lag_o + int(rng.integers(1, 3))
        for (svc, endpoint), lag, rate in (
            (("orders", "POST /orders"), lag_o, 0.9),
            (("gateway", "POST /checkout"), lag_g, 0.8),
        ):
            j = cfg.endpoint_index(svc, endpoint)
            a = min(s + lag, e)
            p.err[a:e, j] = rate
            p.err_mode[a:e, j] = ERR_UPSTREAM
            p.mu[a:e, j] += np.log(1.5)
            ev.affected.append({"service": svc, "endpoint": endpoint, "start_min": a})
    elif ev.type == "latency_drift":
        ev.severity = float(rng.uniform(2.5, 6.0))
        ramp = 1 + (ev.severity - 1) * np.linspace(0, 1, n)
        p.mu[s:e, ep] += np.log(ramp)
        p.warn_rate[s:e, ep] *= ramp
    elif ev.type == "traffic_drop":
        ev.severity = float(rng.uniform(0.5, 0.9))
        p.rate[s:e, ep] *= 1 - ev.severity
    elif ev.type == "novel_error":
        ev.severity = float(rng.uniform(0.002, 0.006))
        p.novel_rate[s:e, ep] = ev.severity
    elif ev.type == "traffic_surge":
        ev.severity = 2.0
        p.rate[s:e, :] *= ev.severity
        ev.affected = [{"service": c.service, "endpoint": c.endpoint, "start_min": s} for c in cfg.endpoints]
    elif ev.type == "deploy":
        ev.severity = 0.0
        p.deploy[s:e, cfg.services.index(ev.service)] = True
    else:  # pragma: no cover
        raise ValueError(ev.type)


def inject(p: Params, rng) -> dict:
    events = schedule(p.cfg, rng)
    for ev in events:
        _apply(p, ev, rng)
    return {
        "faults": [ev.to_label(p.cfg) for ev in events if not ev.benign],
        "benign": [ev.to_label(p.cfg) for ev in events if ev.benign],
    }

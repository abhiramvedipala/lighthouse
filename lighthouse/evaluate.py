"""Incident-level evaluation of detectors against labeled faults.

Units are minute indexes. Flags are per service (a service is flagged in a minute if any of its
endpoints is). Rules, all fixed here and tested in tests/test_evaluate.py:

* Alarm event: flagged minutes of one service merged when at most `merge_gap` unflagged minutes
  lie between them (default 10).
* An incident covers minutes [start, end) on each affected service (the target plus cascade
  victims). It is *detected* if any alarm event of an affected service overlaps
  [start, end - 1 + tolerance] (tolerance 5 minutes, inclusive).
* Precision = alarm events that overlap some real incident window / all alarm events.
  Recall = detected incidents / incidents. False alarms per day = alarm events that overlap no
  incident window / days. Alarm events that overlap only a benign event are false alarms and are
  also counted separately.
* Detection delay = first flagged minute at or after the incident start (inside the window)
  minus start. Lead time = static-alert fire minute minus the detector's first flag minute, on
  incidents both detect.
* Point-adjusted F1 is reported in its own field: if any minute of an incident is flagged, the
  whole incident is counted as flagged. It rewards one lucky flag with a full segment and so
  inflates scores; the headline numbers are the incident-level ones above.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

TOLERANCE = 5
MERGE_GAP = 10


@dataclass(frozen=True)
class Incident:
    id: str
    type: str
    services: frozenset
    start: int          # first minute
    end: int            # exclusive
    benign: bool = False


def alarm_events(flag_minutes: Sequence[int], merge_gap: int = MERGE_GAP) -> list[tuple[int, int]]:
    """Merge sorted flagged minute indexes into inclusive (first, last) alarm events."""
    events: list[tuple[int, int]] = []
    for m in sorted(int(x) for x in flag_minutes):
        if events and m - events[-1][1] - 1 <= merge_gap:
            events[-1] = (events[-1][0], m)
        else:
            events.append((m, m))
    return events


def _window(inc: Incident, tolerance: int) -> tuple[int, int]:
    return inc.start, inc.end - 1 + tolerance


def _overlaps(ev: tuple[int, int], win: tuple[int, int]) -> bool:
    return ev[0] <= win[1] and ev[1] >= win[0]


@dataclass
class Result:
    n_incidents: int = 0
    n_alarm_events: int = 0
    precision: float = float("nan")
    recall: float = float("nan")
    f1: float = 0.0
    false_alarms: int = 0
    false_alarms_per_day: float = 0.0
    false_alarms_per_service_day: float = 0.0
    median_delay: float = float("nan")
    median_lead: float = float("nan")
    n_both: int = 0
    n_detector_only: int = 0
    n_static_only: int = 0
    benign_false_alarms: int = 0
    benign_events_alarmed: int = 0
    n_benign: int = 0
    point_adjusted_f1: float = 0.0
    per_type: dict = field(default_factory=dict)
    per_incident: list = field(default_factory=list)

    def headline(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("per_type", "per_incident")}


def _f1(p: float, r: float) -> float:
    if np.isnan(p) or np.isnan(r) or p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def _first_flag(flags: Mapping[str, np.ndarray], services, lo: int, hi: int, window: tuple[int, int]):
    """First flagged minute in [lo, hi] over `services` (None if no flag in range)."""
    best = None
    for s in services:
        arr = flags.get(s)
        if arr is None:
            continue
        idx = np.flatnonzero(arr[max(lo, window[0]):min(hi, window[1] - 1) + 1])
        if len(idx):
            m = int(idx[0]) + max(lo, window[0])
            best = m if best is None else min(best, m)
    return best


def evaluate(
    flags: Mapping[str, np.ndarray],
    incidents: Sequence[Incident],
    window: tuple[int, int],
    static_flags: Mapping[str, np.ndarray] | None = None,
    tolerance: int = TOLERANCE,
    merge_gap: int = MERGE_GAP,
    n_services: int | None = None,
) -> Result:
    """flags: service -> bool array over absolute minutes. window: [lo, hi) minutes scored.

    Incidents (real and benign, split on `.benign`) are included when they start inside the window.
    """
    lo, hi = window
    days = (hi - lo) / 1440.0
    real = [i for i in incidents if not i.benign and lo <= i.start < hi]
    benign = [i for i in incidents if i.benign and lo <= i.start < hi]
    res = Result(n_incidents=len(real), n_benign=len(benign))

    events: dict[str, list[tuple[int, int]]] = {}
    for svc, arr in flags.items():
        idx = np.flatnonzero(np.asarray(arr[lo:hi], dtype=bool)) + lo
        events[svc] = alarm_events(idx, merge_gap)
    all_events = [(s, e) for s, evs in events.items() for e in evs]
    res.n_alarm_events = len(all_events)

    real_w = [(i, _window(i, tolerance)) for i in real]
    benign_w = [(i, _window(i, tolerance)) for i in benign]
    tp_events = fa_events = benign_only = 0
    alarmed_benign: set[str] = set()
    for svc, ev in all_events:
        hit_real = any(svc in i.services and _overlaps(ev, w) for i, w in real_w)
        hit_ben = [i for i, w in benign_w if svc in i.services and _overlaps(ev, w)]
        if hit_real:
            tp_events += 1
        else:
            fa_events += 1
            if hit_ben:
                benign_only += 1
        alarmed_benign.update(i.id for i in hit_ben)
    res.false_alarms = fa_events
    n_svc = n_services if n_services is not None else max(1, len(flags))
    res.false_alarms_per_day = fa_events / days if days else 0.0
    res.false_alarms_per_service_day = fa_events / (days * n_svc) if days else 0.0
    res.benign_false_alarms = benign_only
    res.benign_events_alarmed = len(alarmed_benign)
    res.precision = tp_events / len(all_events) if all_events else float("nan")

    detected = 0
    delays, leads = [], []
    by_type: dict[str, dict] = defaultdict(lambda: {"n": 0, "detected": 0, "delays": [], "leads": [], "only": 0})
    for inc, w in real_w:
        det = any(
            svc in inc.services and _overlaps(ev, w) for svc, evs in events.items() for ev in evs
        )
        first = _first_flag(flags, inc.services, w[0], w[1], window) if det else None
        if det and first is None:
            first = inc.start  # alarm spans the window through its merge gap but no flag sits inside it
        static_fire = None
        if static_flags is not None:
            static_fire = _first_flag(static_flags, inc.services, w[0], w[1], window)
        row = {"id": inc.id, "type": inc.type, "detected": det, "first_flag": first,
               "delay": None if first is None else first - inc.start, "static_fire": static_fire,
               "lead": None if (first is None or static_fire is None) else static_fire - first}
        res.per_incident.append(row)
        t = by_type[inc.type]
        t["n"] += 1
        if det:
            detected += 1
            t["detected"] += 1
            delays.append(row["delay"])
            t["delays"].append(row["delay"])
            if static_flags is not None and static_fire is None:
                res.n_detector_only += 1
                t["only"] += 1
        elif static_flags is not None and static_fire is not None:
            res.n_static_only += 1
        if row["lead"] is not None:
            res.n_both += 1
            leads.append(row["lead"])
            t["leads"].append(row["lead"])
    res.recall = detected / len(real) if real else float("nan")
    res.f1 = _f1(res.precision, res.recall)
    res.median_delay = float(np.median(delays)) if delays else float("nan")
    res.median_lead = float(np.median(leads)) if leads else float("nan")
    res.per_type = {
        k: {"n": v["n"], "detected": v["detected"], "recall": v["detected"] / v["n"],
            "median_delay": float(np.median(v["delays"])) if v["delays"] else float("nan"),
            "median_lead": float(np.median(v["leads"])) if v["leads"] else float("nan"),
            "detector_only": v["only"]}
        for k, v in by_type.items()
    }
    res.point_adjusted_f1 = point_adjusted_f1(flags, real, window)
    return res


def point_adjusted_f1(flags: Mapping[str, np.ndarray], incidents: Sequence[Incident], window: tuple[int, int]) -> float:
    """Minute-level F1 over (service, minute) after the point-adjust step (see module docstring)."""
    lo, hi = window
    tp = fp = fn = 0
    truth = {s: np.zeros(hi - lo, dtype=bool) for s in flags}
    pred = {s: np.asarray(a[lo:hi], dtype=bool).copy() for s, a in flags.items()}
    for inc in incidents:
        a, b = max(inc.start, lo) - lo, min(inc.end, hi) - lo
        for s in inc.services:
            if s not in truth or a >= b:
                continue
            truth[s][a:b] = True
            if pred[s][a:b].any():
                pred[s][a:b] = True
    for s in flags:
        tp += int((pred[s] & truth[s]).sum())
        fp += int((pred[s] & ~truth[s]).sum())
        fn += int((~pred[s] & truth[s]).sum())
    if tp == 0:
        return 0.0
    return _f1(tp / (tp + fp), tp / (tp + fn))


def incidents_from_labels(labels: dict, start, include_benign: bool = True) -> list[Incident]:
    """Convert labels.json (written by the simulator) to Incidents with minute indexes from `start`."""
    import pandas as pd

    start = pd.Timestamp(start)
    out = []
    for key, benign in (("faults", False), ("benign", True)):
        if benign and not include_benign:
            continue
        for ev in labels.get(key, []):
            s = int((pd.Timestamp(ev["start"]) - start) / pd.Timedelta("1min"))
            e = int((pd.Timestamp(ev["end"]) - start) / pd.Timedelta("1min"))
            out.append(Incident(ev["id"], ev["type"], frozenset(a["service"] for a in ev["affected"]), s, e, benign))
    return sorted(out, key=lambda i: i.start)

"""Turn sampled requests into structured log lines.

Volume rule from the brief: one INFO request line per `info_sample` requests,
plus every WARN and ERROR line. Every line is generated inside an
(minute, endpoint) cell so it carries an endpoint.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
import pandas as pd

from lighthouse.sim.templates import DEPLOY, REQUEST, TEMPLATES, truth_template
from lighthouse.sim.traffic import ERR_UPSTREAM, Params


class LazyFields(dict):
    """format_map helper: a field's random value is only drawn if the template uses it."""

    def __init__(self, rnd: random.Random, status: int = 200, ms: int | None = None):
        super().__init__()
        self.rnd, self.status, self.fixed_ms = rnd, status, ms

    def __missing__(self, key: str) -> str:
        r = self.rnd
        match key:
            case "ip":
                return f"10.{r.randint(0, 255)}.{r.randint(0, 255)}.{r.randint(1, 254)}"
            case "ms":
                return str(self.fixed_ms if self.fixed_ms is not None else int(r.lognormvariate(4, 1)))
            case "id":
                return str(r.randint(1, 99999))
            case "sku":
                return f"SKU-{r.randint(0, 9999):05d}"
            case "uuid":
                return str(r.getrandbits(128).to_bytes(16, "big").hex())
            case "n":
                return str(r.randint(1, 500))
            case "hex":
                return f"{r.getrandbits(32):08x}"
            case "user":
                return f"u{r.randint(0, 99999):05d}"
            case "host":
                return f"inv-db-{r.randint(0, 3)}.internal"
            case "order":
                return f"ORD-{r.randint(0, 9_999_999):07d}"
            case "status":
                return str(self.status)
        raise KeyError(key)


@dataclass(frozen=True)
class Entry:
    tid: str
    level: str
    fmt: str
    service: str


def _catalog(cfg) -> tuple[list[Entry], dict]:
    cat: list[Entry] = []
    idx: dict = {}

    def add(key, e: Entry):
        idx[key] = len(cat)
        cat.append(e)

    for svc, tmpls in TEMPLATES.items():
        for t in tmpls:
            add(t.tid, Entry(t.tid, t.level, t.fmt, svc))
            if t.variant:
                add(t.tid + ".v2", Entry(t.tid + ".v2", t.level, t.variant, svc))
        add(DEPLOY[svc].tid, Entry(DEPLOY[svc].tid, "INFO", DEPLOY[svc].fmt, svc))
    for (svc, ep), fmt in REQUEST.items():
        tid = f"{svc}.req.{ep.replace(' ', '_')}"
        add(tid, Entry(tid, "INFO", fmt, svc))
    return cat, idx


def ground_truth() -> dict[str, str]:
    """tid -> true template with <*> wildcards (for the parser benchmark)."""
    cat, _ = _catalog(None)
    return {e.tid: truth_template(e.fmt) for e in cat}


def _cell_lines(rng, counts: np.ndarray, cfg) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expand per-cell counts into (minute, endpoint, ts_ms) arrays."""
    T, E = counts.shape
    cell = np.repeat(np.arange(T * E, dtype=np.int32), counts.ravel())
    t, e = cell // E, cell % E
    start_ms = int(cfg.start.value // 1_000_000)
    ts = start_ms + t.astype(np.int64) * 60_000 + rng.integers(0, 60_000, size=len(cell))
    return t, e, ts


def generate_logs(p: Params, req: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    cfg = p.cfg
    cat, ix = _catalog(cfg)
    T, E = p.rate.shape
    services = cfg.services
    svc_of_ep = np.array([services.index(e.service) for e in cfg.endpoints])
    start_ms = int(cfg.start.value // 1_000_000)

    t_req = ((req["ts"].to_numpy() - start_ms) // 60_000).astype(np.int32)
    e_req = req["ep"].to_numpy().astype(np.int32)
    n_cell = np.zeros((T, E), dtype=np.int64)
    np.add.at(n_cell, (t_req, e_req), 1)

    parts_ts, parts_ep, parts_cat, parts_lat, parts_status = [], [], [], [], []

    def push(ts, ep, cats, lat=None, status=None):
        parts_ts.append(ts)
        parts_ep.append(ep)
        parts_cat.append(cats)
        parts_lat.append(np.full(len(ts), np.nan, dtype=np.float32) if lat is None else lat)
        parts_status.append(np.full(len(ts), 200, dtype=np.int16) if status is None else status)

    # misc INFO and WARN lines, by service
    for kind, lam in (("info", n_cell / cfg.info_sample), ("warn", n_cell * p.warn_rate)):
        t, e, ts = _cell_lines(rng, rng.poisson(lam), cfg)
        cats = np.zeros(len(ts), dtype=np.int32)
        for s, svc in enumerate(services):
            m = svc_of_ep[e] == s
            choices = [ix[x.tid] for x in TEMPLATES[svc] if x.category == kind]
            cats[m] = rng.choice(choices, size=int(m.sum()))
        push(ts, e.astype(np.int8), cats)

    # request INFO lines (successful requests, sampled) and ERROR lines (all failures)
    failed = req["status"].to_numpy() >= 500
    sample = rng.random(len(req)) < 1.0 / cfg.info_sample
    ok = sample & ~failed
    ep_req_cat = np.array([ix[f"{e.service}.req.{e.endpoint.replace(' ', '_')}"] for e in cfg.endpoints])
    push(
        req["ts"].to_numpy()[ok],
        e_req[ok].astype(np.int8),
        ep_req_cat[e_req[ok]].astype(np.int32),
        req["latency_ms"].to_numpy()[ok],
        req["status"].to_numpy()[ok],
    )

    fi = np.flatnonzero(failed)
    tf, ef = t_req[fi], e_req[fi]
    cats = np.zeros(len(fi), dtype=np.int32)
    novel = req["novel"].to_numpy()[fi]
    mode = p.err_mode[tf, ef]
    dep = p.deploy[tf, svc_of_ep[ef]]
    for s, svc in enumerate(services):
        sm = svc_of_ep[ef] == s
        base = [x for x in TEMPLATES[svc] if x.category == "err_base"]
        up = [ix[x.tid] for x in TEMPLATES[svc] if x.category == "err_up"]
        nov = [ix[x.tid] for x in TEMPLATES[svc] if x.category == "err_novel"]
        w = 1.0 / np.arange(1, len(base) + 1)
        w /= w.sum()
        pick = rng.choice(len(base), size=len(fi), p=w)
        base_cat = np.array([ix[b.tid] for b in base])[pick]
        base_var = np.array([ix[b.tid + ".v2"] for b in base])[pick]
        base_cat = np.where(dep, base_var, base_cat)
        up_cat = rng.choice(up, size=len(fi))
        c = np.where(mode == ERR_UPSTREAM, up_cat, base_cat)
        c = np.where(novel, nov[0], c)
        cats[sm] = c[sm]
    push(req["ts"].to_numpy()[fi], ef.astype(np.int8), cats,
         req["latency_ms"].to_numpy()[fi], req["status"].to_numpy()[fi])

    # deploy marker lines: about one per minute of an active deploy window
    for s, svc in enumerate(services):
        for t in np.flatnonzero(p.deploy[:, s]):
            ep0 = int(np.flatnonzero(svc_of_ep == s)[0])
            push(np.array([start_ms + int(t) * 60_000 + int(rng.integers(0, 60_000))]),
                 np.array([ep0], dtype=np.int8), np.array([ix[DEPLOY[svc].tid]], dtype=np.int32))

    ts = np.concatenate(parts_ts)
    ep = np.concatenate(parts_ep)
    cat_i = np.concatenate(parts_cat)
    lat = np.concatenate(parts_lat)
    status = np.concatenate(parts_status)
    order = np.argsort(ts, kind="stable")
    ts, ep, cat_i, lat, status = ts[order], ep[order], cat_i[order], lat[order], status[order]

    rnd = random.Random(int(rng.integers(0, 2**31)))
    msgs, trace = [], []
    for c, lv, s in zip(cat_i.tolist(), lat.tolist(), status.tolist(), strict=True):
        fields = LazyFields(rnd, s, None if lv != lv else int(lv))
        msgs.append(cat[c].fmt.format_map(fields))
        trace.append(f"{rnd.getrandbits(64):016x}")
    return pd.DataFrame(
        {
            "ts": ts,
            "service": [cat[c].service for c in cat_i],
            "level": [cat[c].level for c in cat_i],
            "message": msgs,
            "trace_id": trace,
            "endpoint": [cfg.endpoints[i].endpoint for i in ep],
            "latency_ms": lat,
            "tid": [cat[c].tid for c in cat_i],
        }
    )

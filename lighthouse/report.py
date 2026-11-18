"""Run every detector end to end and write the results.

Fit on train, pick thresholds on validation, score the test window once. Writes
results/thresholds.json, results/metrics.json, results/tables.md and the charts in docs/.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from lighthouse.data import Dataset, load_dataset
from lighthouse.detectors.iforest import IsolationForestDetector
from lighthouse.detectors.prophet_residual import ProphetResidual
from lighthouse.detectors.seasonal import SeasonalBaseline
from lighthouse.detectors.static import StaticThreshold
from lighthouse.detectors.zscore import RollingZScore
from lighthouse.evaluate import Result, evaluate
from lighthouse.thresholds import flags_from_scores, save_thresholds, select_threshold

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"
FAULT_TYPES = ["latency_spike", "error_burst", "dependency_outage", "latency_drift", "traffic_drop", "novel_error"]
IF_ABLATIONS = {
    "isolation_forest (spec)": {},
    "no residual features": {"residuals": False},
    "no template features": {"templates": False},
    "contaminated train": {"clean_train": False},
    "residual-only features": {"raw": False, "deltas": False},
    "residual-only, per endpoint": {"raw": False, "deltas": False, "per_endpoint": True},
}


def _row(res: Result) -> dict:
    h = res.headline()
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in h.items()}


def run_detector(name, det, ds: Dataset, static_flags, fixed: float | None = None) -> dict:
    t0 = time.perf_counter()
    det.fit(ds, ds.splits["train"])
    scores = det.score(ds)
    secs = time.perf_counter() - t0
    val_w, test_w = ds.splits["val"], ds.splits["test"]
    if fixed is None:
        sel = select_threshold(scores, ds.incidents, val_w)
    else:
        sel = {"threshold": fixed, "feasible": True}
    thr = sel["threshold"]
    flags = flags_from_scores(scores, thr)
    n = len(ds.services)
    val = evaluate(flags, ds.incidents, val_w, static_flags=static_flags, n_services=n)
    test = evaluate(flags, ds.incidents, test_w, static_flags=static_flags, n_services=n)
    return {"name": name, "threshold": thr, "feasible": sel.get("feasible", True), "seconds": round(secs, 1),
            "val": val, "test": test, "scores": scores}


def run_all(ds: Dataset, fast: bool = False, ablations: bool = True, log=print) -> dict:
    t_start = time.perf_counter()
    static = StaticThreshold()
    static_scores = static.score(ds)
    static_flags = flags_from_scores(static_scores, 1.0)
    out = {}
    spec = [
        ("static_threshold", static, 1.0),
        ("rolling_zscore", RollingZScore(), None),
        ("seasonal_baseline", SeasonalBaseline(), None),
        ("isolation_forest", IsolationForestDetector(), None),
        ("prophet_residual", ProphetResidual(uncertainty_samples=50 if fast else 200), None),
    ]
    for name, det, fixed in spec:
        out[name] = run_detector(name, det, ds, static_flags, fixed)
        log(f"{name}: val F1 {out[name]['val'].f1:.3f} test F1 {out[name]['test'].f1:.3f} ({out[name]['seconds']} s)")
    out["ensemble"] = run_ensemble(out, ds, static_flags)
    if ablations:
        out["_ablations"] = {}
        for label, kw in IF_ABLATIONS.items():
            r = run_detector(label, IsolationForestDetector(**kw), ds, static_flags)
            out["_ablations"][label] = r
            log(f"  ablation {label}: val F1 {r['val'].f1:.3f} test F1 {r['test'].f1:.3f}")
    out["_wall_seconds"] = round(time.perf_counter() - t_start, 1)
    out["_static_flags"] = static_flags
    return out


def run_ensemble(out: dict, ds: Dataset, static_flags) -> dict:
    """Max of seasonal, IF and Prophet scores, each divided by its own validation 99.9th percentile."""
    lo, hi = ds.splits["val"]
    parts = []
    for name in ("seasonal_baseline", "isolation_forest", "prophet_residual"):
        s = out[name]["scores"]
        q = float(np.quantile(s.to_numpy()[lo:hi], 0.999)) or 1.0
        parts.append(s / q)
    scores = parts[0].copy()
    for p in parts[1:]:
        scores = np.maximum(scores, p)
    sel = select_threshold(scores, ds.incidents, ds.splits["val"])
    flags = flags_from_scores(scores, sel["threshold"])
    n = len(ds.services)
    val = evaluate(flags, ds.incidents, ds.splits["val"], static_flags=static_flags, n_services=n)
    test = evaluate(flags, ds.incidents, ds.splits["test"], static_flags=static_flags, n_services=n)
    members = max(out[k]["val"].f1 for k in ("seasonal_baseline", "isolation_forest", "prophet_residual"))
    return {"name": "ensemble", "threshold": sel["threshold"], "feasible": sel["feasible"], "seconds": 0.0,
            "val": val, "test": test, "scores": scores, "reported": val.f1 > members}


def fmt(x, nd=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def tables(out: dict, ds: Dataset) -> str:
    names = [k for k in out if not k.startswith("_")]
    lines = ["| Detector | Precision | Recall | F1 | False alarms/day | Median delay (min) | Median lead vs static (min) "
             "| Detector-only catches | Benign-event alarms | Point-adjusted F1 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        if n == "ensemble" and not out[n]["reported"]:
            continue
        r = out[n]["test"]
        lead = "reference" if n == "static_threshold" else fmt(r.median_lead, 1)
        lines.append(f"| {n} | {fmt(r.precision)} | {fmt(r.recall)} | {fmt(r.f1)} | {fmt(r.false_alarms_per_day)} | "
                     f"{fmt(r.median_delay, 1)} | {lead} | {r.n_detector_only if n != 'static_threshold' else '-'} | "
                     f"{r.benign_false_alarms} ({r.benign_events_alarmed}/{r.n_benign} events) | {fmt(r.point_adjusted_f1)} |")
    lines += ["", "Recall per fault type on the test window (detected / incidents):", "",
              "| Detector | " + " | ".join(FAULT_TYPES) + " |", "|---|" + "---|" * len(FAULT_TYPES)]
    for n in names:
        if n == "ensemble" and not out[n]["reported"]:
            continue
        pt = out[n]["test"].per_type
        cells = [f"{pt[t]['detected']}/{pt[t]['n']}" if t in pt else "-" for t in FAULT_TYPES]
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    lines += ["", "Validation (where thresholds were chosen): "
              + "; ".join(f"{n} F1 {fmt(out[n]['val'].f1)} at threshold {fmt(out[n]['threshold'], 3)}"
                          + ("" if out[n]["feasible"] else " (infeasible)") for n in names if n != "static_threshold")]
    if "_ablations" in out:
        lines += ["", "Isolation Forest ablations (thresholds on validation, scored on test):", "",
                  "| Variant | Val F1 | Test precision | Test recall | Test F1 | False alarms/day |", "|---|---|---|---|---|---|"]
        for label, r in out["_ablations"].items():
            t = r["test"]
            lines.append(f"| {label} | {fmt(r['val'].f1)} | {fmt(t.precision)} | {fmt(t.recall)} | {fmt(t.f1)} | "
                         f"{fmt(t.false_alarms_per_day)} |")
    return "\n".join(lines)


def charts(out: dict, ds: Dataset) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [n for n in ("rolling_zscore", "seasonal_baseline", "isolation_forest", "prophet_residual")]
    leads = [[p["lead"] for p in out[n]["test"].per_incident if p["lead"] is not None] for n in names]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(leads, tick_labels=[f"{n}\n(n={len(v)})" for n, v in zip(names, leads, strict=True)])
    ax.axhline(0, color="gray", lw=0.8)
    ax.axhline(2, color="tab:green", ls="--", lw=0.8, label="2 min target")
    ax.set_ylabel("lead over static alert (min)")
    ax.set_title("Lead time on incidents both catch (test window)")
    ax.legend()
    fig.tight_layout()
    DOCS.mkdir(exist_ok=True)
    fig.savefig(DOCS / "lead_time.png", dpi=110)
    plt.close(fig)

    inc = out["seasonal_baseline"]["test"].per_incident
    dets = ["static_threshold", "seasonal_baseline", "isolation_forest", "prophet_residual"]
    colors = dict(zip(dets, ["black", "tab:blue", "tab:orange", "tab:green"], strict=True))
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(inc) + 2))
    lo = ds.splits["test"][0]
    for i, row in enumerate(inc):
        real = next(x for x in ds.incidents if x.id == row["id"])
        ax.barh(i, real.end - real.start, left=real.start - lo, color="tab:red", alpha=0.25)
        for n in dets:
            r = next(p for p in out[n]["test"].per_incident if p["id"] == row["id"])
            if r["first_flag"] is not None:
                ax.plot(r["first_flag"] - lo, i, "o", color=colors[n], ms=4, label=n if i == 0 else None)
    ax.set_yticks(range(len(inc)))
    ax.set_yticklabels([r["id"] for r in inc], fontsize=7)
    ax.set_xlabel("minutes into the test window")
    ax.set_title("Incidents (red) and each detector's first flag")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(DOCS / "incident_timeline.png", dpi=110)
    plt.close(fig)


def write_outputs(out: dict, ds: Dataset, results_dir: Path = RESULTS) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    names = [k for k in out if not k.startswith("_")]
    save_thresholds({n: {"threshold": out[n]["threshold"], "feasible": out[n]["feasible"],
                         "val_f1": out[n]["val"].f1} for n in names}, results_dir / "thresholds.json")
    metrics = {n: {"test": _row(out[n]["test"]), "val": _row(out[n]["val"]), "per_type": out[n]["test"].per_type,
                   "seconds": out[n]["seconds"]} for n in names}
    metrics["_wall_seconds"] = out["_wall_seconds"]
    (results_dir / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (results_dir / "tables.md").write_text(tables(out, ds) + "\n")


def main(argv=None) -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="full 14-day simulator run")
    ap.add_argument("--fixture", action="store_true", help="smoke run on the committed 2-day fixture")
    a = ap.parse_args(argv)
    if a.fixture:
        ds = load_dataset("fixture")
        out = run_all(ds, fast=True, ablations=False)
        print(tables(out, ds))
        print(f"fixture eval {out['_wall_seconds']} s")
        return
    ds = load_dataset("sim")
    out = run_all(ds)
    write_outputs(out, ds)
    charts(out, ds)
    print(tables(out, ds))
    print(f"offline train+evaluate wall-clock: {out['_wall_seconds']} s")


if __name__ == "__main__":
    main()

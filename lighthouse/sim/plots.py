"""One plot per fault type: rate, error rate and p95 around an example incident."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def minute_series(cfg, req: pd.DataFrame, ep: int) -> pd.DataFrame:
    r = req[req["ep"] == ep]
    t = ((r["ts"] - cfg.start.value // 1_000_000) // 60_000).astype(int)
    g = r.groupby(t)
    out = pd.DataFrame({
        "rate": g.size(),
        "err": g["status"].apply(lambda s: (s >= 500).mean()),
        "p95": g["latency_ms"].quantile(0.95),
    }).reindex(range(cfg.minutes))
    out.index = pd.date_range(cfg.start, periods=cfg.minutes, freq="min")
    return out


def plot_event(cfg, req, ev: dict, path: Path, pad_min: int = 180) -> None:
    ep = cfg.endpoint_index(ev["service"], ev["endpoint"])
    s, e = pd.Timestamp(ev["start"]), pd.Timestamp(ev["end"])
    pad = pd.Timedelta(minutes=pad_min + max(0, (e - s) // pd.Timedelta("1min")) // 2)
    st = minute_series(cfg, req, ep).loc[s - pad:e + pad]
    fig, axes = plt.subplots(3, 1, figsize=(8, 6), sharex=True)
    for ax, col, lab in zip(axes, ("rate", "err", "p95"), ("requests/min", "error rate", "p95 ms"), strict=True):
        ax.plot(st.index, st[col].rolling(3, min_periods=1).mean(), lw=1)
        ax.axvspan(s, e, color="tab:red", alpha=0.15)
        ax.set_ylabel(lab)
    axes[0].set_title(f"{ev['type']} on {ev['service']} {ev['endpoint']} (severity {ev['severity']:.2f})")
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_all(cfg, req, labels: dict, out: Path) -> list[Path]:
    paths, seen = [], set()
    for ev in labels["faults"] + labels["benign"]:
        if ev["type"] in seen:
            continue
        seen.add(ev["type"])
        p = out / f"{ev['type']}.png"
        plot_event(cfg, req, ev, p)
        paths.append(p)
    return paths


if __name__ == "__main__":
    from lighthouse.sim.config import load_sim_config
    from lighthouse.sim.run import simulate

    cfg = load_sim_config()
    _, req, _, labels = simulate(cfg)
    for p in plot_all(cfg, req, labels, Path("docs/faults")):
        print(p)

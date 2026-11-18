"""Diagnosis only: where do each detector's test-window false alarms fall (by day)? Reads, never tunes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

from lighthouse.data import load_dataset  # noqa: E402
from lighthouse.evaluate import alarm_events  # noqa: E402
from lighthouse.report import run_all  # noqa: E402
from lighthouse.thresholds import flags_from_scores  # noqa: E402

ds = load_dataset("sim")
out = run_all(ds, ablations=False, log=lambda *_: None)
lo, hi = ds.splits["test"]
real = [i for i in ds.incidents if not i.benign]
print("false-alarm events per test day (Thu, Fri, Sat, Sun)")
for n in ("rolling_zscore", "seasonal_baseline", "isolation_forest", "prophet_residual"):
    fl = flags_from_scores(out[n]["scores"], out[n]["threshold"])
    per_day = np.zeros(4, dtype=int)
    for svc, arr in fl.items():
        for s, e in alarm_events(np.flatnonzero(arr[lo:hi]) + lo):
            if not any(svc in i.services and s <= i.end + 4 and e >= i.start for i in real):
                per_day[min((s - lo) // 1440, 3)] += 1
    print(f"{n:20s}", per_day.tolist())

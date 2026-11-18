import json

from lighthouse.data import load_dataset
from lighthouse.detectors.iforest import IsolationForestDetector
from lighthouse.detectors.seasonal import SeasonalBaseline
from lighthouse.detectors.static import StaticThreshold
from lighthouse.detectors.zscore import RollingZScore
from lighthouse.report import _row, run_detector, tables, write_outputs
from lighthouse.thresholds import flags_from_scores


def _run(ds):
    sf = flags_from_scores(StaticThreshold().score(ds), 1.0)
    res = {}
    for name, det, fixed in (("static_threshold", StaticThreshold(), 1.0), ("rolling_zscore", RollingZScore(), None),
                             ("seasonal_baseline", SeasonalBaseline(), None),
                             ("isolation_forest", IsolationForestDetector(n_estimators=50), None)):
        res[name] = run_detector(name, det, ds, sf, fixed)
    return res


def test_same_seed_gives_identical_incident_level_metrics():
    ds = load_dataset("fixture")
    a, b = _run(ds), _run(ds)
    for n in a:
        assert _row(a[n]["test"]) == _row(b[n]["test"])
        assert a[n]["threshold"] == b[n]["threshold"]


def test_outputs_are_written(tmp_path):
    ds = load_dataset("fixture")
    out = _run(ds)
    out["ensemble"] = {**out["seasonal_baseline"], "reported": False}
    out["_wall_seconds"] = 1.0
    write_outputs(out, ds, tmp_path)
    assert set(json.loads((tmp_path / "thresholds.json").read_text())) >= {"static_threshold", "seasonal_baseline"}
    assert "| seasonal_baseline |" in (tmp_path / "tables.md").read_text()
    assert "ensemble" not in tables(out, ds).split("Validation")[0]

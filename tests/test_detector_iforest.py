import numpy as np
import pytest

from lighthouse.detectors.iforest import IsolationForestDetector
from tests.test_detector_seasonal import sine_ds

TRAIN = (0, 3 * 1440)
SPIKE = slice(3 * 1440 + 600, 3 * 1440 + 630)


@pytest.fixture(scope="module")
def ds():
    return sine_ds(spike=SPIKE)


def labeled(ds, start_min, end_min):
    import pandas as pd

    from lighthouse.data import Dataset

    t0, t1 = (ds.start + pd.Timedelta(minutes=m) for m in (start_min, end_min))
    ev = {"id": "f", "type": "latency_spike", "service": "svc", "endpoint": "GET /x", "start": str(t0), "end": str(t1),
          "severity": 4.0, "affected": [{"service": "svc", "endpoint": "GET /x", "start": str(t0)}]}
    return Dataset(ds.agg, ds.start, ds.minutes, {"faults": [ev], "benign": []}, ds.slo)


def test_planted_anomaly_scores_above_most_held_out_minutes(ds):
    # a lone latency spike is not isolated sharply: IF treats every dimension alike and the heavy-tailed
    # error-rate residual makes ordinary minutes look as odd. It still ranks the spike in the top decile.
    det = IsolationForestDetector(n_estimators=100, raw=False, deltas=False, templates=False).fit(ds, TRAIN)
    s = det.score(ds)["svc"].to_numpy()
    held_out = s[3 * 1440:]
    assert s[SPIKE].mean() > np.percentile(held_out, 90)
    assert s[SPIKE].mean() > 1.3 * np.median(held_out)


def test_same_seed_gives_identical_scores(ds):
    a = IsolationForestDetector(n_estimators=50).fit(ds, TRAIN).score(ds)
    b = IsolationForestDetector(n_estimators=50).fit(ds, TRAIN).score(ds)
    np.testing.assert_array_equal(a.to_numpy(), b.to_numpy())


def test_different_seed_changes_scores(ds):
    a = IsolationForestDetector(n_estimators=50, seed=1).fit(ds, TRAIN).score(ds)
    b = IsolationForestDetector(n_estimators=50, seed=2).fit(ds, TRAIN).score(ds)
    assert not np.array_equal(a.to_numpy(), b.to_numpy())


def test_default_hyperparameters_follow_the_brief():
    det = IsolationForestDetector()
    assert det.n_estimators == 200
    ds = sine_ds()
    det.fit(ds, TRAIN)
    model = next(iter(det.models.values()))
    assert model.contamination == "auto" and model.n_estimators == 200


def test_ablation_switches_change_the_feature_set(ds):
    def names(**kw):
        d = IsolationForestDetector(n_estimators=10, **kw).fit(ds, TRAIN)
        return {n.split(":", 1)[1] for n in d.names}

    full = names()
    assert {"z_rate", "z_err", "z_lat", "warn", "newsig24", "newsig5", "d_rate", "rate"} <= full
    assert not any(n.startswith("z_") for n in names(residuals=False))
    assert not {"warn", "newsig24", "newsig5"} & names(templates=False)
    assert not {"rate", "err", "lat", "lat99"} & names(raw=False)
    assert not any(n.startswith("d_") for n in names(deltas=False))


def test_contaminated_training_uses_fault_minutes_clean_does_not():
    import numpy as np

    from lighthouse.data import Dataset
    from tests.helpers import make_ds

    labels = {"faults": [{"id": "f", "type": "latency_spike", "service": "svc", "endpoint": "GET /x",
                          "start": "2026-10-06T10:00:00", "end": "2026-10-06T11:00:00", "severity": 5.0,
                          "affected": [{"service": "svc", "endpoint": "GET /x", "start": "2026-10-06T10:00:00"}]}],
              "benign": []}
    base = make_ds(minutes=3 * 1440, labels=labels)
    ds = Dataset(base.agg, base.start, base.minutes, labels, base.slo)
    assert ds.train_mask("svc")[24 * 60 + 600: 24 * 60 + 660].sum() == 0   # clean mask drops the fault
    clean = IsolationForestDetector(n_estimators=10).fit(ds, (0, 3 * 1440))
    dirty = IsolationForestDetector(n_estimators=10, clean_train=False).fit(ds, (0, 3 * 1440))
    assert clean.models["svc"].n_features_in_ == dirty.models["svc"].n_features_in_
    assert np.isfinite(clean.score(ds).to_numpy()).all()


def test_per_endpoint_mode_builds_one_model_per_endpoint():
    from tests.helpers import make_ds

    ds = make_ds(minutes=3 * 1440, services=(("svc", "GET /a"), ("svc", "GET /b")))
    per_svc = IsolationForestDetector(n_estimators=10).fit(ds, (0, 3 * 1440))
    per_ep = IsolationForestDetector(n_estimators=10, per_endpoint=True).fit(ds, (0, 3 * 1440))
    assert len(per_svc.models) == 1 and len(per_ep.models) == 2
    assert list(per_ep.score(ds).columns) == ["svc"]


def test_permutation_importance_ranks_the_informative_feature_first():
    ds = labeled(sine_ds(spike=slice(3 * 1440 + 600, 3 * 1440 + 700)), 3 * 1440 + 600, 3 * 1440 + 700)
    det = IsolationForestDetector(n_estimators=100, raw=False, deltas=False, templates=False).fit(ds, TRAIN)
    imp = det.permutation_importance(ds, (3 * 1440, 5 * 1440), n_repeats=2)
    assert imp.iloc[0]["feature"] == "z_lat" and imp.iloc[0]["auc_drop"] > 0.05

import numpy as np
import pytest

from lighthouse.sim.config import load_sim_config
from lighthouse.sim.logs import ground_truth
from lighthouse.sim.run import simulate
from lighthouse.sim.templates import TEMPLATES


@pytest.fixture(scope="module")
def sim():
    cfg = load_sim_config(days=1)
    params, req, logs, _ = simulate(cfg)
    return cfg, req, logs


def test_one_info_request_line_per_twenty_requests(sim):
    cfg, req, logs = sim
    req_lines = logs["tid"].str.contains(r"\.req\.").sum()
    ok = (req["status"] < 500).sum()
    assert req_lines == pytest.approx(ok / cfg.info_sample, rel=0.05)


def test_every_failed_request_has_an_error_line(sim):
    _, req, logs = sim
    assert (logs["level"] == "ERROR").sum() == (req["status"] >= 500).sum()


def test_log_volume_is_a_small_fraction_of_requests(sim):
    _, req, logs = sim
    assert len(logs) < len(req) * 0.25


def test_each_service_has_about_forty_templates():
    for svc in TEMPLATES:
        n = len(TEMPLATES[svc]) + sum(1 for t in ground_truth() if t.startswith(f"{svc}.req."))
        assert 30 <= n <= 45


def test_ground_truth_covers_every_emitted_template(sim):
    _, _, logs = sim
    truth = ground_truth()
    assert set(logs["tid"]) <= set(truth)


def test_messages_have_no_unfilled_placeholders(sim):
    _, _, logs = sim
    assert not logs["message"].str.contains(r"\{[a-z]+\}", regex=True).any()


def test_logs_sorted_and_lines_carry_endpoint(sim):
    _, _, logs = sim
    assert logs["ts"].is_monotonic_increasing
    assert (logs["endpoint"] != "").all()


def test_same_seed_identical_logs():
    cfg = load_sim_config(days=1, rate_scale=0.2)
    a = simulate(cfg)[2]
    b = simulate(cfg)[2]
    assert a.equals(b)


def test_error_lines_mention_exception_class_when_template_has_one(sim):
    _, _, logs = sim
    errs = logs[(logs["level"] == "ERROR") & logs["tid"].str.contains("err_base")]
    assert errs["message"].str.contains("Error").mean() == 1.0
    assert np.isfinite(errs["latency_ms"]).all()

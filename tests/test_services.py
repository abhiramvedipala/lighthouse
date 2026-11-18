import time

import pytest
from starlette.testclient import TestClient

from lighthouse.services.app import create_app
from lighthouse.services.telemetry import Telemetry

TOKEN = "t0ken"


@pytest.fixture()
def stack():
    tel = {s: Telemetry(s) for s in ("gateway", "orders", "inventory")}
    kw = {"latency_scale": 0.01, "token": TOKEN, "base_error_rate": 0.0}  # no random 0.3 percent errors in tests
    inv = create_app("inventory", tel["inventory"], **kw)
    orders = create_app("orders", tel["orders"], downstream={"inventory": TestClient(inv)}, **kw)
    gw = create_app("gateway", tel["gateway"], downstream={"orders": TestClient(orders)}, **kw)
    apps = {"gateway": gw, "orders": orders, "inventory": inv}
    return {n: TestClient(a, raise_server_exceptions=False) for n, a in apps.items()}, tel


def fault(client, **body):
    return client.post("/admin/fault", json=body, headers={"x-admin-token": TOKEN})


def test_checkout_produces_one_trace_across_all_three_services(stack):
    clients, tel = stack
    for _ in range(40):  # base error rate 0.3 percent: nearly all succeed
        assert clients["gateway"].post("/checkout").status_code in (200, 503, 500)
    by_service = {s: tel[s].spans.get_finished_spans() for s in tel}
    assert all(len(v) >= 30 for v in by_service.values())
    gw_traces = {sp.context.trace_id for sp in by_service["gateway"]}
    traces = gw_traces & {sp.context.trace_id for sp in by_service["inventory"]}
    assert len(traces) >= 30  # the call chain is one trace id from gateway to inventory
    assert {sp.name for sp in by_service["orders"]} == {"POST /orders"}


def test_metrics_count_requests_and_record_duration(stack):
    clients, tel = stack
    for _ in range(10):
        clients["inventory"].get("/stock/SKU-00001")
    data = tel["inventory"].metric_reader.get_metrics_data()
    metrics = {m.name: m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    assert sum(p.value for p in metrics["http.server.request.count"].data.data_points) == 10
    hist = metrics["http.server.request.duration"].data.data_points[0]
    assert hist.count == 10 and hist.sum > 0


def test_logs_carry_trace_ids_and_simulator_templates(stack):
    clients, tel = stack
    fault(clients["inventory"], type="error_burst", duration_s=30, severity=1.0)
    for _ in range(5):
        clients["inventory"].get("/stock/SKU-00001")
    logs = tel["inventory"].logs.get_finished_logs()
    errs = [lg.log_record for lg in logs if lg.log_record.severity_text == "ERROR"]
    assert len(errs) == 5
    assert all(e.trace_id and e.trace_id != 0 for e in errs)
    assert all("{" not in e.body for e in errs) and any("Error" in e.body for e in errs)


def test_dependency_outage_cascades_as_503_up_the_chain(stack):
    clients, tel = stack
    assert fault(clients["inventory"], type="dependency_outage", duration_s=30).status_code == 200
    assert clients["inventory"].get("/stock/SKU-00001").status_code == 503
    assert clients["orders"].post("/orders").status_code == 503
    assert clients["gateway"].post("/checkout").status_code == 503
    assert fault(clients["inventory"], type="clear", duration_s=1).status_code == 200
    assert clients["gateway"].post("/checkout").status_code == 200


def test_admin_fault_refuses_without_or_with_wrong_token(stack):
    clients, _ = stack
    assert clients["gateway"].post("/admin/fault", json={"type": "error_burst"}).status_code == 401
    r = clients["gateway"].post("/admin/fault", json={"type": "error_burst"}, headers={"x-admin-token": "nope"})
    assert r.status_code == 401
    assert fault(clients["gateway"], type="not_a_fault").status_code == 422


def test_service_without_a_configured_token_refuses_everything():
    app = create_app("inventory", Telemetry("inventory"), token="", latency_scale=0.01)
    r = TestClient(app).post("/admin/fault", json={"type": "clear"}, headers={"x-admin-token": ""})
    assert r.status_code == 401


def test_latency_spike_slows_requests_and_expires(stack):
    clients, _ = stack
    def timed():
        t = time.perf_counter()
        clients["inventory"].get("/stock/SKU-00001")
        return time.perf_counter() - t
    base = sorted(timed() for _ in range(15))[7]
    fault(clients["inventory"], type="latency_spike", duration_s=0.5, severity=500.0)
    spiked = sorted(timed() for _ in range(5))[2]
    assert spiked > 5 * base
    time.sleep(0.6)
    assert sorted(timed() for _ in range(15))[7] < 5 * base


def test_traffic_drop_swallows_requests_without_telemetry(stack):
    clients, tel = stack
    fault(clients["gateway"], type="traffic_drop", duration_s=30, severity=1.0)
    assert clients["gateway"].get("/products").status_code == 204
    assert not tel["gateway"].spans.get_finished_spans()

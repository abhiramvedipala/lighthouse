"""The three demo services: gateway, orders, inventory (FastAPI + OpenTelemetry).

Topology: gateway POST /checkout -> orders POST /orders -> inventory GET /stock/{sku}, so an inventory
outage cascades up as 503s. Log lines come from the simulator's templates so the live parser sees the
same message shapes. POST /admin/fault (header X-Admin-Token) turns a fault on for a duration.
"""
from __future__ import annotations

import logging
import math
import os
import random
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import context as otel_ctx
from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode

from lighthouse.services.telemetry import Telemetry
from lighthouse.sim.config import load_sim_config
from lighthouse.sim.logs import LazyFields
from lighthouse.sim.templates import DEPLOY, REQUEST, TEMPLATES

FAULTS = ("latency_spike", "error_burst", "dependency_outage", "latency_drift", "traffic_drop", "novel_error", "deploy", "clear")
CALLS = {"gateway": ("orders", "POST", "/orders"), "orders": ("inventory", "GET", "/stock/SKU-00001")}


class State:
    """Active fault for one service."""

    def __init__(self):
        self.type, self.until, self.started, self.severity = None, 0.0, 0.0, 1.0
        self.lock = threading.Lock()

    def set(self, ftype: str, duration: float, severity: float) -> None:
        with self.lock:
            self.type = None if ftype == "clear" else ftype
            self.started, self.until, self.severity = time.monotonic(), time.monotonic() + duration, severity

    def active(self) -> tuple[str | None, float, float]:
        """(type, severity, progress 0..1) of the live fault, or (None, 0, 0)."""
        now = time.monotonic()
        with self.lock:
            if self.type and now < self.until:
                return self.type, self.severity, (now - self.started) / max(self.until - self.started, 1e-9)
        return None, 0.0, 0.0


def create_app(service: str, telemetry: Telemetry | None = None, downstream: dict | None = None,
               token: str | None = None, latency_scale: float | None = None, seed: int = 1,
               base_error_rate: float | None = None) -> FastAPI:
    cfg = load_sim_config()
    eps = {e.endpoint: e for e in cfg.endpoints if e.service == service}
    tel = telemetry or Telemetry(service, os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    token = token if token is not None else os.environ.get("ADMIN_TOKEN", "")
    scale = latency_scale if latency_scale is not None else float(os.environ.get("LATENCY_SCALE", "0.5"))
    base_err = cfg.base_error_rate if base_error_rate is None else base_error_rate
    rnd, state, app = random.Random(seed), State(), FastAPI(title=f"lighthouse-{service}")
    app.state.telemetry, app.state.fault = tel, state
    clients = downstream if downstream is not None else {}

    def client_for(name: str):
        if name not in clients:
            clients[name] = httpx.Client(base_url=os.environ.get(f"{name.upper()}_URL", f"http://{name}:8000"), timeout=5.0)
        return clients[name]

    def emit(level: int, template, status: int = 200, latency_ms: float | None = None, endpoint: str = "") -> None:
        fields = LazyFields(rnd, status, None if latency_ms is None else int(latency_ms))
        msg = template.format_map(fields)
        tel.logger.log(level, msg, extra={"lighthouse.endpoint": endpoint, "lighthouse.status": status,
                                          "lighthouse.template": template})

    def pick(category: str):
        items = [t for t in TEMPLATES[service] if t.category == category]
        return items[rnd.randrange(len(items))]

    def error_template(ftype: str | None):
        if ftype == "dependency_outage":
            return pick("err_up").fmt
        if ftype == "novel_error":
            return pick("err_novel").fmt
        base = [t for t in TEMPLATES[service] if t.category == "err_base"]
        t = base[min(int(rnd.expovariate(1.0)), len(base) - 1)]
        return t.variant if state.active()[0] == "deploy" and t.variant else t.fmt

    def handle(endpoint: str, call_downstream: bool, request: Request):
        ep = eps[endpoint]
        ftype, sev, prog = state.active()
        if ftype == "traffic_drop" and rnd.random() < sev:
            return Response(status_code=204)  # swallowed before any telemetry, like an upstream routing fault
        ctx = propagate.extract(dict(request.headers))
        t0 = time.perf_counter()
        status, err_fmt = 200, None
        with tel.tracer.start_as_current_span(endpoint, context=ctx, kind=SpanKind.SERVER,
                                              attributes={"http.route": endpoint, "service.endpoint": endpoint}) as span:
            lat = rnd.lognormvariate(math.log(ep.p50_ms * scale), ep.sigma)
            if ftype == "latency_spike":
                lat *= sev
            elif ftype == "latency_drift":
                lat *= 1 + (sev - 1) * prog
            time.sleep(lat / 1000)
            if ftype == "dependency_outage" and service == "inventory":
                status, err_fmt = 503, error_template(ftype)
            elif ftype == "error_burst" and rnd.random() < sev:
                status, err_fmt = 500, error_template(None)
            elif ftype == "novel_error" and rnd.random() < sev:
                status, err_fmt = 500, error_template(ftype)
            elif rnd.random() < base_err:
                status, err_fmt = 500, error_template(None)
            if call_downstream and status == 200:
                name, method, path = CALLS[service]
                headers: dict = {}
                propagate.inject(headers)
                try:
                    r = client_for(name).request(method, path, headers=headers)
                    if r.status_code >= 500:
                        status, err_fmt = 503, error_template("dependency_outage")
                except httpx.HTTPError:
                    status, err_fmt = 503, error_template("dependency_outage")
            elapsed = (time.perf_counter() - t0) * 1000
            span.set_attribute("http.status_code", status)
            if status >= 500:
                span.set_status(Status(StatusCode.ERROR))
            attrs = {"service": service, "endpoint": endpoint, "status": str(status)}
            tel.requests.add(1, attrs)
            tel.duration.record(elapsed, attrs)
            if status >= 500:
                emit(logging.ERROR, err_fmt, status, elapsed, endpoint)
            else:
                if rnd.random() < 1 / cfg.info_sample:
                    emit(logging.INFO, REQUEST[(service, endpoint)], status, elapsed, endpoint)
                if rnd.random() < 0.05:
                    emit(logging.INFO, pick("info").fmt, 200, None, endpoint)
                if rnd.random() < 0.02 * (4 if ftype in ("latency_spike", "latency_drift") else 1):
                    emit(logging.WARNING, pick("warn").fmt, 200, None, endpoint)
            if ftype == "deploy" and rnd.random() < 0.2:
                emit(logging.INFO, DEPLOY[service].fmt, 200, None, endpoint)
        if status >= 500:
            raise HTTPException(status_code=status, detail="error")
        return {"ok": True, "service": service}

    routes = {
        "gateway": [("GET", "/products", "GET /products", False), ("POST", "/checkout", "POST /checkout", True)],
        "orders": [("POST", "/orders", "POST /orders", True), ("GET", "/orders/{order_id}", "GET /orders/{id}", False)],
        "inventory": [("GET", "/stock/{sku}", "GET /stock/{sku}", False)],
    }[service]
    for method, path, endpoint, down in routes:
        def make(endpoint=endpoint, down=down):
            def route(request: Request):
                return handle(endpoint, down, request)
            return route
        app.add_api_route(path, make(), methods=[method])

    @app.post("/admin/fault")
    def admin_fault(body: dict, request: Request):
        sent = request.headers.get("x-admin-token")
        if not token or sent != token:
            raise HTTPException(status_code=401, detail="admin token required")
        ftype = body.get("type")
        if ftype not in FAULTS:
            raise HTTPException(status_code=422, detail=f"type must be one of {FAULTS}")
        state.set(ftype, float(body.get("duration_s", 60)), float(body.get("severity", 5.0)))
        return {"fault": ftype, "duration_s": body.get("duration_s", 60)}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.state.otel_ctx = otel_ctx
    return app

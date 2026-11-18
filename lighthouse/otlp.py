"""Decode OTLP JSON (the collector's `otlp_json` Kafka encoding) into small records."""
from __future__ import annotations

import json
from dataclasses import dataclass

SEVERITY = {"SEVERITY_NUMBER_ERROR": "ERROR", "SEVERITY_NUMBER_WARN": "WARN", "SEVERITY_NUMBER_INFO": "INFO"}


@dataclass(frozen=True)
class LogRec:
    ts_ms: int
    service: str
    level: str
    body: str
    endpoint: str


@dataclass(frozen=True)
class SpanRec:
    end_ms: int
    service: str
    endpoint: str
    duration_ms: float
    error: bool
    status: int


def attrs(items: list | None) -> dict:
    out = {}
    for a in items or []:
        v = a.get("value", {})
        out[a["key"]] = next(iter(v.values())) if v else None
    return out


def _service(resource: dict) -> str:
    return str(attrs(resource.get("attributes")).get("service.name", "unknown"))


def _level(rec: dict) -> str:
    text = (rec.get("severityText") or "").upper()
    if text in ("ERROR", "WARN", "WARNING", "INFO"):
        return "WARN" if text == "WARNING" else text
    n = int(rec.get("severityNumber", 9) or 9)
    return "ERROR" if n >= 17 else "WARN" if n >= 13 else "INFO"


def decode_logs(raw: bytes | str) -> list[LogRec]:
    out = []
    for rl in json.loads(raw).get("resourceLogs", []):
        svc = _service(rl.get("resource", {}))
        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                a = attrs(rec.get("attributes"))
                body = (rec.get("body") or {}).get("stringValue", "")
                out.append(LogRec(int(rec["timeUnixNano"]) // 1_000_000, svc, _level(rec), body,
                                  str(a.get("lighthouse.endpoint", ""))))
    return out


def decode_spans(raw: bytes | str) -> list[SpanRec]:
    out = []
    for rs in json.loads(raw).get("resourceSpans", []):
        svc = _service(rs.get("resource", {}))
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                a = attrs(sp.get("attributes"))
                start, end = int(sp["startTimeUnixNano"]), int(sp["endTimeUnixNano"])
                status = int(a.get("http.status_code", 200) or 200)
                code = (sp.get("status") or {}).get("code")
                err = status >= 500 or code in (2, "STATUS_CODE_ERROR")
                out.append(SpanRec(end // 1_000_000, svc, str(a.get("service.endpoint", sp.get("name", ""))),
                                   (end - start) / 1e6, err, status))
    return out

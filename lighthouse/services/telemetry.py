"""OpenTelemetry setup for one service: traces, metrics and logs, to OTLP gRPC or to memory (tests)."""
from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class Telemetry:
    """Providers are kept on the object (never the global ones) so several services can share a process."""

    def __init__(self, service: str, endpoint: str | None = None):
        res = Resource.create({"service.name": service})
        self.spans = self.logs = self.metric_reader = None
        self.tracer_provider = TracerProvider(resource=res)
        self.logger_provider = LoggerProvider(resource=res)
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            self.tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
            self.logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True)))
            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint, insecure=True),
                                                   export_interval_millis=10_000)
        else:
            self.spans, self.logs, self.metric_reader = InMemorySpanExporter(), InMemoryLogRecordExporter(), InMemoryMetricReader()
            self.tracer_provider.add_span_processor(SimpleSpanProcessor(self.spans))
            self.logger_provider.add_log_record_processor(SimpleLogRecordProcessor(self.logs))
            reader = self.metric_reader
        self.meter_provider = MeterProvider(resource=res, metric_readers=[reader])
        self.tracer = self.tracer_provider.get_tracer(service)
        meter = self.meter_provider.get_meter(service)
        self.requests = meter.create_counter("http.server.request.count", description="requests handled")
        self.duration = meter.create_histogram("http.server.request.duration", unit="ms", description="request duration")
        self.logger = logging.getLogger(f"lighthouse.{service}.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=self.logger_provider))

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


__all__ = ["Telemetry", "metrics", "trace"]

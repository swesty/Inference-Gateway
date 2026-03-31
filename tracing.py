"""Optional OpenTelemetry distributed tracing setup."""

from __future__ import annotations

import os


def setup_tracing(app=None) -> None:
    """Configure OTLP tracing if OTEL_EXPORTER_OTLP_ENDPOINT is set.

    No-ops silently when the env var is unset or OTEL packages are missing.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "inference-gateway"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()


def get_trace_id() -> str | None:
    """Return the current trace ID as a hex string, or None if tracing is inactive."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id != 0:
            return format(ctx.trace_id, "032x")
    except ImportError:
        pass
    return None

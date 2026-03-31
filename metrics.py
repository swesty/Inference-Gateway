"""Prometheus metric definitions and helpers."""

from __future__ import annotations

import os
import time

from prometheus_client import Counter, Histogram, Info, start_http_server

from technique import get_server_profile

_LABELS = ["technique", "server_profile"]

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "End-to-end request latency",
    _LABELS,
)

TIME_TO_FIRST_TOKEN = Histogram(
    "time_to_first_token_seconds",
    "Time from request start to first streaming token",
    _LABELS,
)

INTER_CHUNK_DELAY = Histogram(
    "stream_inter_chunk_delay_seconds",
    "Delay between consecutive streaming chunks",
    _LABELS,
)

TIME_PER_OUTPUT_TOKEN = Histogram(
    "time_per_output_token_seconds",
    "Average time per output token",
    _LABELS,
)

COMPLETION_TOKENS_PER_SECOND = Histogram(
    "completion_tokens_per_second",
    "Completion token throughput",
    _LABELS,
)

PROMPT_TOKENS = Counter(
    "prompt_tokens_total",
    "Total prompt tokens processed",
    _LABELS,
)

COMPLETION_TOKENS = Counter(
    "completion_tokens_total",
    "Total completion tokens generated",
    _LABELS,
)

REQUESTS_TOTAL = Counter(
    "requests_total",
    "Total requests processed",
    _LABELS,
)

GATEWAY_INFO = Info("llm_gateway", "Gateway instance metadata")
GATEWAY_INFO.info({"server_profile": get_server_profile()})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def record_request_metrics(
    technique: str,
    duration: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record metrics for a completed (non-streaming) request."""
    profile = get_server_profile()
    labels = {"technique": technique, "server_profile": profile}
    REQUESTS_TOTAL.labels(**labels).inc()
    REQUEST_DURATION.labels(**labels).observe(duration)
    if prompt_tokens:
        PROMPT_TOKENS.labels(**labels).inc(prompt_tokens)
    if completion_tokens:
        COMPLETION_TOKENS.labels(**labels).inc(completion_tokens)
        if duration > 0:
            COMPLETION_TOKENS_PER_SECOND.labels(**labels).observe(completion_tokens / duration)
            TIME_PER_OUTPUT_TOKEN.labels(**labels).observe(duration / completion_tokens)


def record_streaming_metrics(
    technique: str,
    duration: float,
    ttft: float | None = None,
    chunk_delays: list[float] | None = None,
) -> None:
    """Record metrics for a completed streaming request."""
    profile = get_server_profile()
    labels = {"technique": technique, "server_profile": profile}
    REQUESTS_TOTAL.labels(**labels).inc()
    REQUEST_DURATION.labels(**labels).observe(duration)
    if ttft is not None:
        TIME_TO_FIRST_TOKEN.labels(**labels).observe(ttft)
    if chunk_delays:
        for delay in chunk_delays:
            INTER_CHUNK_DELAY.labels(**labels).observe(delay)


def get_metrics_summary() -> dict:
    """Return a JSON-friendly summary of key metrics."""
    profile = get_server_profile()
    summary: dict = {"server_profile": profile, "techniques": {}}

    for technique in ("baseline", "beam_search", "chunked_prefill", "speculative"):
        labels = {"technique": technique, "server_profile": profile}
        req_count = REQUESTS_TOTAL.labels(**labels)._value.get()
        if req_count == 0:
            continue
        summary["techniques"][technique] = {
            "requests": int(req_count),
            "avg_duration_s": round(
                REQUEST_DURATION.labels(**labels)._sum.get() / req_count, 4
            ),
        }

    return summary


def start_metrics_server() -> None:
    """Start the Prometheus HTTP server on the metrics port."""
    port = int(os.environ.get("METRICS_PORT", "9101"))
    start_http_server(port)

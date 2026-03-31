# Observability

The gateway implements all three pillars of observability: **metrics**, **logs**, and **traces**.

## Prometheus Metrics

Exposed on `:9101/metrics` in Prometheus text format. All metrics include labels `technique` and `server_profile`.

### Histograms

| Metric | Description | When Recorded |
|--------|-------------|---------------|
| `request_duration_seconds` | End-to-end request latency | Every request |
| `time_to_first_token_seconds` | Time from request start to first streaming chunk | Streaming requests only |
| `stream_inter_chunk_delay_seconds` | Delay between consecutive streaming chunks | Streaming requests only |
| `time_per_output_token_seconds` | Average time per completion token | Non-streaming with completion tokens |
| `completion_tokens_per_second` | Completion token throughput | Non-streaming with completion tokens |

### Counters

| Metric | Description |
|--------|-------------|
| `requests_total` | Total requests processed |
| `prompt_tokens_total` | Total prompt tokens processed |
| `completion_tokens_total` | Total completion tokens generated |
| `estimated_gpu_cost_usd_total` | Cumulative estimated GPU cost in USD |

### Info

| Metric | Description |
|--------|-------------|
| `llm_gateway_info` | Gateway instance metadata (includes `server_profile`) |

### Labels

| Label | Source | Purpose |
|-------|--------|---------|
| `technique` | `X-Technique` header, `metadata.technique`, or `"baseline"` | Group metrics by request type / engine configuration |
| `server_profile` | `VLLM_SERVER_PROFILE` env var (default `"default"`) | Identify which engine configuration is running |

### JSON Summary

`GET /metrics/summary` returns a human-readable JSON summary:

```json
{
  "server_profile": "default",
  "techniques": {
    "baseline": {"requests": 42, "avg_duration_s": 0.5234},
    "beam_search": {"requests": 10, "avg_duration_s": 1.2345}
  }
}
```

Only techniques with at least one request are included.

---

## JSONL Request Logging

Every request produces one JSON line in a daily-rotated file.

**Directory:** `GATEWAY_METRICS_LOG_DIR` (default `logs/gateway`, set to `"-"` to disable)

**Filename:** `gateway_metrics_YYYY-MM-DD.jsonl` (UTC date)

### Log Entry Fields

```json
{
  "timestamp": "2026-03-30T12:34:56.123456+00:00",
  "request_id": "uuid-or-client-provided",
  "technique": "baseline",
  "server_profile": "default",
  "backend": "vllm_remote",
  "duration_s": 0.523456,
  "prompt_tokens": 10,
  "completion_tokens": 20,
  "cost_usd": 0.00016,
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "stream": false,
  "status_code": 200
}
```

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 UTC timestamp |
| `request_id` | string | Request ID (from header or generated) |
| `technique` | string | Resolved technique label |
| `server_profile` | string | From `VLLM_SERVER_PROFILE` env var |
| `backend` | string | Backend name that handled the request |
| `duration_s` | float | End-to-end duration in seconds |
| `prompt_tokens` | int | Prompt token count (from backend response) |
| `completion_tokens` | int | Completion token count (from backend response) |
| `cost_usd` | float | Estimated GPU cost for this request |
| `trace_id` | string/null | OpenTelemetry trace ID (null if tracing disabled) |
| `stream` | bool | Whether the request was streaming |
| `status_code` | int | HTTP status code returned |

### Querying Logs

```bash
# All requests for a specific technique
jq 'select(.technique == "beam_search")' logs/gateway/gateway_metrics_2026-03-30.jsonl

# Average duration by technique
jq -s 'group_by(.technique) | map({technique: .[0].technique, avg_duration: (map(.duration_s) | add / length)})' logs/gateway/*.jsonl

# Find a specific request
jq 'select(.request_id == "my-req-1")' logs/gateway/*.jsonl
```

---

## OpenTelemetry Distributed Tracing

Optional. Zero overhead when disabled.

### Setup

1. Install tracing dependencies:
   ```bash
   uv sync --extra tracing
   ```

2. Set environment variables:
   ```bash
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   OTEL_SERVICE_NAME=inference-gateway  # optional, this is the default
   ```

3. Start a collector (e.g. Jaeger):
   ```bash
   docker run -d --name jaeger -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one:latest
   ```

4. Restart the gateway — tracing activates automatically.

### What's Traced

- **FastAPI requests** — auto-instrumented via `FastAPIInstrumentor`
- **httpx calls** — auto-instrumented via `HTTPXClientInstrumentor` (backend calls)
- **Trace ID** — propagated to JSONL logs (`trace_id` field) and available via `get_trace_id()`

### Viewing Traces

Open Jaeger UI at `http://localhost:16686`. Select service `inference-gateway` to see request spans.

### Disabling

Leave `OTEL_EXPORTER_OTLP_ENDPOINT` unset. The `setup_tracing()` function returns immediately, no OTEL code is loaded, and there is zero runtime overhead.

---

## Cost Tracking

Per-request GPU cost estimated from request duration.

**Formula:** `cost_usd = (duration_seconds / 3600) × GPU_HOURLY_COST_USD`

### Configuration

**Manual rate:**
```bash
GPU_HOURLY_COST_USD=1.10  # $1.10/hour for Lambda A10
```

**Automatic rate (Lambda Cloud API):**
```bash
LAMBDA_API_KEY=your_key_here
```
Fetches pricing once at startup, caches the result. Falls back to `GPU_HOURLY_COST_USD` (default `0.0`) if the API is unavailable.

### Where Cost Appears

- **Prometheus:** `estimated_gpu_cost_usd_total` counter (cumulative)
- **JSONL logs:** `cost_usd` field per request
- **Grafana:** "Estimated GPU Cost" panel in the overview dashboard

---

## Monitoring Stack (Docker Compose)

```bash
docker compose up -d
```

| Service | Port | Purpose |
|---------|------|---------|
| gateway | 8080, 9101 | Application + metrics |
| nginx | 8780 | Load balancer |
| prometheus | 9090 | Metrics storage + querying |
| grafana | 3000 | Dashboards (admin/admin) |

### Prometheus Scrape Config

`monitoring/prometheus.yml` scrapes `gateway:9101/metrics` every 15 seconds.

### Grafana Dashboards

Pre-provisioned at startup. Located in `monitoring/grafana/dashboards/`:

**Gateway Overview** (`gateway-overview.json`):
- Request rate by technique (req/s)
- Request duration percentiles (p50/p95/p99)
- Total requests, prompt tokens, completion tokens (stat panels)
- Estimated GPU cost (USD)
- Time to first token (streaming)
- Tokens per second

### Verifying the Stack

1. Open http://localhost:9090/targets — gateway should be **UP**
2. Open http://localhost:3000 → Dashboards → Inference Gateway
3. Send a request, wait 15–30s for Prometheus to scrape, refresh dashboard

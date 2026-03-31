# Inference Gateway

A minimal, OpenAI-compatible HTTP inference gateway. Routes `POST /v1/chat/completions` to named backends defined in `config.yaml`, with request-ID tracking, streaming support, Prometheus metrics, and optional OpenTelemetry tracing.

Built with FastAPI + uvicorn.

## Quick Start

```bash
uv sync
uv run python app.py
```

The server starts on port 8080 by default. See [Cloud Deployment Guide](docs/cloud-deployment.md) for GPU setup.

### Docker

```bash
docker compose up -d
# Gateway: http://localhost:8080
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000 (admin/admin)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Gateway listen port |
| `VLLM_TLS_VERIFY` | `true` | TLS verification for vLLM backends |
| `VLLM_SERVER_PROFILE` | `default` | Server profile label for metrics |
| `GPU_HOURLY_COST_USD` | `0.0` | GPU cost for per-request estimation |
| `GATEWAY_METRICS_LOG_DIR` | `logs/gateway` | JSONL log directory (`-` to disable) |
| `METRICS_PORT` | `9101` | Prometheus scrape port |

See `.env.example` for the full list including engine routing and cloud deployment vars.

## Configuration

Backends are defined in `config.yaml`. If no config file is found, the gateway runs with a single echo backend.

```yaml
default_backend: echo
# fallback_backend: echo
backends:
  echo:
    type: echo
  local:
    type: local
    url: http://127.0.0.1:8081
```

- **`default_backend`** — name of the backend used when the request has no `model` or an unknown model.
- **`fallback_backend`** *(optional)* — name of a backend to try when the primary backend fails (connection error, timeout, HTTP error). Must reference a backend defined in `backends`. Omit or comment out to disable fallback.
- **`backends`** — map of named backends. Each entry needs a `type` (`echo` for echo mode, anything else for remote) and remote backends need a `url`.

## Model Routing

Requests are routed by the `model` field:

1. If `model` matches a registered backend name → route to that backend
2. Otherwise → route to `default_backend`

### Echo Backend

Echoes the last user message back with an `Echo: ` prefix. Useful for testing.

### Remote Backend

Forwards requests to an upstream OpenAI-compatible API at the configured `url`.

## Endpoints

### `GET /healthz`

Liveness probe.

```bash
curl http://localhost:8080/healthz
# {"status":"ok"}
```

### `GET /health`

Readiness probe with backend connectivity checks.

```bash
curl http://localhost:8080/health
# {"status":"healthy","backends":[{"name":"echo","type":"echo","status":"ok"}]}
```

### `GET /metrics/summary`

JSON summary of Prometheus metrics.

```bash
curl http://localhost:8080/metrics/summary
```

### `GET /v1/models`

List available models.

```bash
curl http://localhost:8080/v1/models
```

### `GET /v1/backends`

List registered backends with their name, type, and whether they are the default.

```bash
curl http://localhost:8080/v1/backends
# {"backends":[{"name":"echo","type":"echo","default":true}]}
```

### `POST /v1/chat/completions`

Chat completion (non-streaming):

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: test-1" \
  -d '{"messages":[{"role":"user","content":"Hello!"}]}'
```

Chat completion (streaming):

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

## Request Validation

Incoming requests to `/v1/chat/completions` are validated before processing. Invalid requests receive a `400` response with a JSON error body.

| Field         | Rules                                                        | Error key             |
|---------------|--------------------------------------------------------------|-----------------------|
| `messages`    | Required. Array of objects, each with `role` (str) and `content` (str). | `invalid_messages`    |
| `stream`      | Optional. Must be a boolean.                                 | `invalid_stream`      |
| `max_tokens`  | Optional. Integer in `[1, 128000]`.                          | `invalid_max_tokens`  |
| `model`       | Optional. Must be a string. Used for routing (see [Model Routing](#model-routing)). | `invalid_model`       |
| `temperature` | Optional. Number in `[0.0, 2.0]`.                            | `invalid_temperature` |
| `stop`        | Optional. String or array of strings.                        | `invalid_stop`        |

Accepted requests are normalized: unrecognized fields are stripped, and `stream` defaults to `false` if omitted.

## Error Handling

When a remote backend is configured, the gateway handles failures gracefully:

| Scenario                  | HTTP Status | Response body                          |
|---------------------------|-------------|----------------------------------------|
| Backend HTTP error        | 502         | `{"error": "backend_error"}`           |
| Connection failure        | 502         | `{"error": "backend_unavailable"}`     |
| Read/write error          | 502         | `{"error": "backend_error"}`           |
| Backend timeout           | 504         | `{"error": "gateway_timeout"}`         |
| Non-JSON backend response | 502         | `{"error": "backend_error"}`           |

### Fallback

When `fallback_backend` is configured and the primary backend fails, the gateway automatically retries the request against the fallback backend. On a successful fallback:

- The `X-Fallback: true` response header is set.
- For non-streaming responses, the body includes `"fallback": true`.

If no fallback is configured, or the fallback is the same backend that failed, the original error is returned.

## Request ID Tracking

The gateway reads `X-Request-ID` or `Request-Id` from incoming headers. If neither is present, a UUID is generated. The request ID appears in both the response body (`id` field) and the `X-Request-ID` response header.

## Testing

```bash
# Bash/curl tests
bash test_gateway.sh

# Python stdlib tests
uv run python test_gateway.py
```

## Workloads and Experiments

LangChain test workloads live in `workloads/` (separate project):

```bash
cd workloads && uv sync
uv run python workload.py --technique baseline
```

Experiment scripts:

```bash
# Technique sweep
./scripts/run_experiments.sh

# A/B test
./scripts/run_server_ab.sh baseline beam_search
```

## Load Balancer

An nginx reverse proxy distributes requests across gateway workers (round-robin on port 8780):

```bash
# Via Docker Compose (starts automatically)
docker compose up -d
curl http://localhost:8780/healthz

# Standalone
nginx -p /tmp -c "$(pwd)/monitoring/nginx-gateway-lb.conf"
```

Set `GATEWAY_USE_LOAD_BALANCER=true` and point clients to port 8780 instead of 8080. For multi-worker setups, add additional `server` lines in `monitoring/nginx-gateway-lb.conf`.

## Cloud Deployment

See [docs/cloud-deployment.md](docs/cloud-deployment.md) for deploying with a remote GPU via SSH tunnel (Lambda Cloud / Anyscale).

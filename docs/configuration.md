# Configuration

## config.yaml

Backends are defined in `config.yaml` at the project root. If no config file is found, the gateway runs with a single echo backend.

```yaml
default_backend: echo
fallback_backend: echo          # optional
backends:
  echo:
    type: echo

  vllm_remote:
    type: vllm
    url: http://localhost:8000

  modal:
    type: remote
    url: https://your-modal-url.modal.run
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `default_backend` | Yes | Name of the backend used when `model` is absent or unknown |
| `fallback_backend` | No | Backend to try when the primary fails. Must reference a defined backend. |
| `backends` | Yes | Map of backend name → config |

### Backend Types

| Type | Class | Description |
|------|-------|-------------|
| `echo` | `EchoBackend` | Returns "Echo: {last user message}". No `url` needed. |
| `remote` | `RemoteBackend` | Forwards to any OpenAI-compatible API. Requires `url`. |
| `vllm` | `VllmBackend` | Extends `RemoteBackend` with beam search injection and TLS verify. Requires `url`. |

Each backend entry needs:
- `type` — one of the above (defaults to the backend name if omitted)
- `url` — required for `remote` and `vllm` types

### VllmBackend Specifics

`VllmBackend` subclasses `RemoteBackend` with two additions:

1. **Beam search injection** — when `technique="beam_search"`, automatically injects `use_beam_search=True` and `best_of=4` into the request body. The `technique` field is stripped before forwarding (vLLM rejects unknown fields).

2. **TLS verification** — controlled by `VLLM_TLS_VERIFY` env var (default `true`). Set to `false` for self-signed certs.

---

## Environment Variables

All env vars can be set in a `.env` file (loaded via `python-dotenv` at startup). See `.env.example` for the full template.

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Gateway listen port |
| `METRICS_PORT` | `9101` | Prometheus scrape port (separate HTTP server) |

### vLLM Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_TLS_VERIFY` | `true` | TLS certificate verification for vLLM backends. Set to `false` for self-signed certs. |
| `VLLM_SERVER_PROFILE` | `"default"` | Label for metrics/logging. Set to identify which engine config is running (e.g. `baseline`, `chunked_prefill_v1`). Change and restart gateway when switching engine configs. |

### Engine Routing

Optional. Pick one strategy or leave both unset for normal registry-based routing.

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_BACKEND_MAP_JSON` | unset | Explicit technique → URL mapping as JSON. Example: `{"baseline":"http://localhost:8000","chunked_prefill":"http://localhost:8001"}` |
| `VLLM_AUTO_ENGINE_ROUTING` | unset | Set to `true` to enable auto port-offset routing: baseline=+0, chunked_prefill=+1, speculative=+2, beam_search=+3 applied to the default backend's port. |

### Cost Tracking

| Variable | Default | Description |
|----------|---------|-------------|
| `GPU_HOURLY_COST_USD` | `0.0` | GPU cost per hour in USD. Cost per request = `(duration_s / 3600) * rate`. |
| `LAMBDA_API_KEY` | unset | Lambda Cloud API key for automatic pricing lookup. Fetched once at startup, cached. Falls back to `GPU_HOURLY_COST_USD` if unavailable. |

### Request Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_METRICS_LOG_DIR` | `logs/gateway` | Directory for JSONL request logs. Set to `"-"` to disable logging entirely. |

### Distributed Tracing

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP gRPC endpoint (e.g. `http://localhost:4317`). If unset, tracing is completely disabled (zero overhead). |
| `OTEL_SERVICE_NAME` | `inference-gateway` | Service name in traces. |

Install tracing dependencies separately: `uv sync --extra tracing`

### Load Balancer

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_USE_LOAD_BALANCER` | `false` | When `true`, clients should connect to nginx LB port instead of gateway directly. |
| `GATEWAY_LB_HOST` | `localhost` | Load balancer hostname. |
| `GATEWAY_LB_PORT` | `8780` | Load balancer port. |

### Cloud / SSH Tunnel

| Variable | Default | Description |
|----------|---------|-------------|
| `SSH_HOST` | unset | SSH host for tunnel (e.g. `ubuntu@192.168.1.100`). Used by `scripts/ssh_tunnel.sh`. |
| `SSH_KEY` | `~/.ssh/id_ed25519` | Path to SSH private key. |
| `LOCAL_PORT` | `8081` | Local port for SSH tunnel. |
| `REMOTE_PORT` | `8000` | Remote vLLM port. |

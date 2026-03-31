# API Reference

## Health & Readiness

### `GET /healthz`

Liveness probe. Always returns 200 if the process is running.

```bash
curl http://localhost:8080/healthz
```

```json
{"status": "ok"}
```

### `GET /health`

Readiness probe. Checks connectivity to all configured backends (5s timeout per backend).

```bash
curl http://localhost:8080/health
```

```json
{
  "status": "healthy",
  "backends": [
    {"name": "echo", "type": "echo", "status": "ok"},
    {"name": "vllm_remote", "type": "vllm", "status": "ok"}
  ]
}
```

**Status values:**
- `healthy` — all backends return `"ok"`
- `degraded` — at least one `"ok"`, at least one `"error"`
- `unhealthy` — all backends failed

**Error details** (when a backend fails):

| Detail | Meaning |
|--------|---------|
| `placeholder URL` | URL contains `YOUR_` — not configured |
| `HTML response (not an API)` | Backend returned HTML, not JSON |
| `connection refused` | Backend not running or wrong port |
| `timeout` | Backend didn't respond within 5s |
| `HTTP 500` (etc.) | Backend returned an error status |

---

## Models & Backends

### `GET /v1/models`

List available models (one per backend).

```bash
curl http://localhost:8080/v1/models
```

```json
{
  "object": "list",
  "data": [
    {"id": "echo", "object": "model", "created": 0, "owned_by": "inference-gateway"},
    {"id": "vllm_remote", "object": "model", "created": 0, "owned_by": "inference-gateway"}
  ]
}
```

### `GET /v1/backends`

List backends with type and default status.

```bash
curl http://localhost:8080/v1/backends
```

```json
{
  "backends": [
    {"name": "echo", "type": "echo", "default": true},
    {"name": "vllm_remote", "type": "vllm", "default": false}
  ]
}
```

---

## Metrics

### `GET /metrics/summary`

JSON summary of Prometheus metrics, grouped by technique.

```bash
curl http://localhost:8080/metrics/summary
```

```json
{
  "server_profile": "default",
  "techniques": {
    "baseline": {
      "requests": 42,
      "avg_duration_s": 0.5234
    }
  }
}
```

### `GET :9101/metrics`

Prometheus text format (separate port). Used by Prometheus scraper.

```bash
curl http://localhost:9101/metrics
```

---

## Chat Completions

### `POST /v1/chat/completions`

OpenAI-compatible chat completion endpoint. Supports streaming and non-streaming.

#### Request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: my-req-1" \
  -H "X-Technique: baseline" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "model": "echo",
    "stream": false,
    "max_tokens": 100,
    "temperature": 0.7,
    "stop": ["\n"],
    "metadata": {"technique": "baseline"}
  }'
```

**Request fields:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `messages` | `array[{role: str, content: str}]` | Yes | Non-empty array of dicts |
| `model` | `string` | No | Routes to named backend if it exists |
| `stream` | `boolean` | No | Defaults to `false` |
| `max_tokens` | `integer` | No | Must be in `[1, 128000]` |
| `temperature` | `number` | No | Must be in `[0.0, 2.0]` |
| `stop` | `string` or `array[string]` | No | Stop sequences |
| `metadata` | `object` | No | `metadata.technique` used for technique resolution |

**Request headers:**

| Header | Purpose |
|--------|---------|
| `X-Request-ID` | Client-provided request ID (or auto-generated UUID) |
| `X-Technique` | Technique label (highest priority for resolution) |

#### Non-Streaming Response (200)

```json
{
  "id": "my-req-1",
  "object": "chat.completion",
  "created": 1711800000,
  "model": "echo",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Echo: Hello!"},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 2,
    "completion_tokens": 3,
    "total_tokens": 5
  }
}
```

**Response headers:**

| Header | Value |
|--------|-------|
| `X-Request-ID` | Request ID (echoed back) |
| `X-Technique` | Resolved technique label |
| `X-Fallback` | `"true"` only if fallback backend was used |

#### Streaming Response (200)

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

Response is `Content-Type: text/event-stream`:

```
data: {"id":"req-123","object":"chat.completion.chunk","created":1711800000,"model":"echo","choices":[{"index":0,"delta":{"content":"Echo: Hi"},"finish_reason":null}]}

data: {"id":"req-123","object":"chat.completion.chunk","created":1711800000,"model":"echo","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]

```

#### Error Responses

| Status | Error Key | When |
|--------|-----------|------|
| 400 | `invalid_messages` | Missing, non-array, or malformed messages |
| 400 | `invalid_stream` | `stream` is not a boolean |
| 400 | `invalid_max_tokens` | Not int or out of `[1, 128000]` |
| 400 | `invalid_model` | `model` is not a string |
| 400 | `invalid_temperature` | Not number or out of `[0.0, 2.0]` |
| 400 | `invalid_stop` | Not string or array of strings |
| 502 | `backend_error` | Upstream HTTP error, read/write error, or non-JSON response |
| 502 | `backend_unavailable` | Cannot connect to upstream |
| 504 | `gateway_timeout` | Upstream didn't respond within 120s |

#### Routing Logic

1. If engine routing env vars are set and technique matches → route to engine-specific backend
2. Else if `model` matches a registered backend name → route to that backend
3. Else → route to `default_backend`

#### Normalization

Before forwarding, the gateway:
- Strips all fields not in: `messages`, `stream`, `max_tokens`, `model`, `temperature`, `stop`, `metadata`
- Defaults `stream` to `false` if not provided

# Inference Gateway

A minimal, OpenAI-compatible HTTP inference gateway. Routes `POST /v1/chat/completions` to named backends defined in `config.yaml`, with request-ID tracking and streaming support.

Built with FastAPI + uvicorn.

## Quick Start

```bash
uv sync
uv run python app.py
```

The server starts on port 8080 by default.

## Environment Variables

| Variable | Default | Description       |
|----------|---------|-------------------|
| `PORT`   | `8080`  | Port to listen on |

## Configuration

Backends are defined in `config.yaml`. If no config file is found, the gateway runs with a single echo backend.

```yaml
default_backend: echo
backends:
  echo:
    type: echo
  local:
    type: local
    url: http://127.0.0.1:8081
```

- **`default_backend`** — name of the backend used when the request has no `model` or an unknown model.
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

Health check.

```bash
curl http://localhost:8080/healthz
# {"status":"ok"}
```

### `GET /v1/models`

List available models.

```bash
curl http://localhost:8080/v1/models
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

## Request ID Tracking

The gateway reads `X-Request-ID` or `Request-Id` from incoming headers. If neither is present, a UUID is generated. The request ID appears in both the response body (`id` field) and the `X-Request-ID` response header.

## Testing

```bash
# Bash/curl tests
bash test_gateway.sh

# Python stdlib tests
uv run python test_gateway.py
```

# Inference Gateway

A minimal, OpenAI-compatible HTTP inference gateway. Accepts `POST /v1/chat/completions`, forwards to a configurable backend or echoes the request, and returns properly shaped responses with request-ID tracking.

Built with FastAPI + uvicorn.

## Quick Start

```bash
uv sync
uv run python app.py
```

The server starts on port 8080 by default.

## Environment Variables

| Variable      | Default | Description                                                       |
|---------------|---------|-------------------------------------------------------------------|
| `PORT`        | `8080`  | Port to listen on                                                 |
| `BACKEND_URL` | *(empty)* | Upstream base URL (e.g. `http://localhost:11434`). If unset, echo mode is used. |

## Modes

### Echo Mode (default)

When `BACKEND_URL` is not set, the gateway echoes the last user message back with an `Echo: ` prefix. Useful for testing.

### Backend Forwarding

Set `BACKEND_URL` to proxy requests to an OpenAI-compatible backend:

```bash
BACKEND_URL=http://localhost:11434 uv run python app.py
```

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
| `model`       | Optional. Must be a string. Defaults to `"echo"`.            | `invalid_model`       |
| `temperature` | Optional. Number in `[0.0, 2.0]`.                            | `invalid_temperature` |
| `stop`        | Optional. String or array of strings.                        | `invalid_stop`        |

Accepted requests are normalized: unrecognized fields are stripped, and `model` and `stream` receive defaults if omitted.

## Error Handling

When `BACKEND_URL` is configured, the gateway handles backend failures gracefully:

| Scenario                  | HTTP Status | Behavior                                      |
|---------------------------|-------------|-----------------------------------------------|
| Backend HTTP error        | 502         | Returns `{"error": "Backend error: <status>"}` |
| Connection failure        | 502         | Returns `{"error": "Backend connection failed: ..."}` |
| Read/write error          | 502         | Returns `{"error": "Backend read/write failed: ..."}` |
| Backend timeout           | 504         | Returns `{"error": "Backend request timed out"}` |
| Non-JSON backend response | 502         | Returns `{"error": "Backend returned non-JSON response"}` |

For both streaming and non-streaming requests, if the backend is unreachable or returns an error, the gateway falls back to echo mode automatically.

## Request ID Tracking

The gateway reads `X-Request-ID` or `Request-Id` from incoming headers. If neither is present, a UUID is generated. The request ID appears in both the response body (`id` field) and the `X-Request-ID` response header.

## Testing

```bash
# Bash/curl tests
bash test_gateway.sh

# Python stdlib tests
uv run python test_gateway.py
```

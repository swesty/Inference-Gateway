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

## Request ID Tracking

The gateway reads `X-Request-ID` or `Request-Id` from incoming headers. If neither is present, a UUID is generated. The request ID appears in both the response body (`id` field) and the `X-Request-ID` response header.

## Testing

```bash
# Bash/curl tests
bash test_gateway.sh

# Python stdlib tests
uv run python test_gateway.py
```

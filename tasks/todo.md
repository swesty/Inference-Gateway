# Multi-Backend Gateway — Implementation Tasks

> Architecture overview and diagrams: `reference/architecture-overview.md`

---

## Step 1 — Backend ABC + Echo & Remote Backends (Issue #6)

**Goal:** Define the interface. Wrap existing echo/forward logic in classes. No behavior change.

**New files:**
- `backends/backend.py` — ABC with `generate()` and `info()`
- `backends/echo.py` — `EchoBackend`, moves `echo_response()` + `echo_stream()` here
- `backends/remote.py` — `RemoteBackend`, moves `forward_to_backend()` + `_stream_lines()` here
- `backends/__init__.py` — re-exports

**`generate()` contract:**
```
async generate(prompt, request_id, stream=False)
  → stream=False: returns response dict (same shape as build_response output)
  → stream=True:  returns async generator of SSE strings
```

**What moves where:**
- `gateway.py` lines 172-181 (echo logic) → `EchoBackend.generate()`
- `gateway.py` lines 189-228 (forwarding) → `RemoteBackend.generate()`
- `gateway.py` lines 119-164 (response builders) → stay in `gateway.py`
- Delete `backends/backend_interface.py` (replaced by `backends/backend.py`)

**Key detail:** `RemoteBackend.__init__(self, name, url)` stores the URL. No more global `BACKEND_URL`.

**Done when:** All 14 existing tests pass unchanged. `app.py` still uses the old if/else — wired up in Step 3.

---

## Step 2 — Config-Driven Backend Registry (Issue #7)

**Goal:** A registry that reads YAML config and instantiates backends by type.

**New files:**
- `config.py` — `BackendRegistry` class
- `config.yaml` — sample config

**Registry API:**
```python
registry = BackendRegistry.from_config("config.yaml")
registry.get("echo")        # → EchoBackend
registry.get("openai")      # → RemoteBackend
registry.get_default()      # → whatever default_backend points to
registry.get_fallback()     # → fallback backend or None
registry.list_backends()    # → list of all Backend instances
```

**Config shape:**
```yaml
default_backend: echo
# fallback_backend: echo   # opt-in, added in Step 6
backends:
  echo:
    type: echo
  openai:
    type: remote
    url: https://api.openai.com/v1
```

**Env var overrides:**
- `GATEWAY_CONFIG` → config file path (default: `config.yaml`)
- `DEFAULT_BACKEND` → overrides `default_backend`
- `BACKEND_<NAME>_URL` → overrides url for a named backend

**Backward compat:** No config file? Auto-register echo backend only (today's behavior).

**Dependency:** Add `pyyaml` to `pyproject.toml`, run `uv sync`.

**Done when:** Registry loads config, tests pass. `app.py` not wired up yet.

---

## Step 3 — Model Routing + Backend Metadata (Issue #8)

**Goal:** Wire it all together. `app.py` uses registry, one code path, no branching.

**Changes to `app.py`:**
```python
# startup: registry = BackendRegistry.from_config(...)
# handler:
#   model = body.get("model")
#   backend = registry.get(model) if model else registry.get_default()
#   result = await backend.generate(prompt, request_id, stream)
```

**Changes to `gateway.py`:**
- `build_response()` gains optional `backend=None` param → adds `"backend": name` to output
- `build_sse_chunk()` same treatment
- `normalize_request_body()` stops defaulting `model` to `"echo"` — registry handles defaults now

**Response change:** Every response now includes `"backend": "echo"` (or whichever served it).

**Done when:** Existing tests updated for `backend` field. New routing tests:
- `model: "echo"` → echo backend
- No model → default backend
- Unknown model → default backend (or error — your design choice)

---

## Step 4 — Dynamic /v1/models (Issue #9)

**Goal:** `/v1/models` lists all configured backends, not just hardcoded echo.

**Change in `app.py`:**
```python
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": b.name, "object": "model", "created": 0, "owned_by": "inference-gateway"}
            for b in registry.list_backends()
        ],
    }
```

**Done when:** Test confirms all configured backends appear in the list.

---

## Step 5 — GET /v1/backends Endpoint (Issue #10)

**Goal:** New introspection endpoint showing backend details + status.

**New route in `app.py`:** `GET /v1/backends`

**Each backend implements `info()`:**
```python
# EchoBackend.info()
{"name": "echo", "type": "echo", "status": "available"}

# RemoteBackend.info()
{"name": "openai", "type": "remote", "url": "https://...", "status": "available"}
```

**Registry adds the `"default": true/false` flag** — backends don't know if they're default.

**Response shape:**
```json
{
  "backends": [
    {"name": "echo", "type": "echo", "status": "available", "default": true},
    {"name": "openai", "type": "remote", "url": "https://...", "status": "available", "default": false}
  ]
}
```

**Done when:** New tests verify the endpoint shape and default flag.

## Kept this simpler for the time being since I'm not sure we'll need a whole `info()` method. If so we'll add it later

---

## Step 6 — Configurable Fallback Backend (Issue #11)

**Goal:** Opt-in fallback. Primary fails → retry with fallback backend → signal fallback in both response body and header.

**Config addition:**
```yaml
fallback_backend: echo
```

**Fallback signaling — two layers:**

1. **`X-Fallback: true` response header** — always set when fallback is used (streaming + non-streaming, any backend type). This is the universal signal.
2. **`"fallback": true` in response body** — set via dict mutation after `generate()` returns. Works for non-streaming only (both echo and remote return dicts). For streaming, the header is the only signal.

**Logic in `app.py` handler:**
```python
try:
    result = await backend.generate(...)
    used_fallback = False
except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException,
        httpx.ReadError, httpx.WriteError, BackendJSONError):
    fallback = registry.get_fallback()
    if fallback is None:
        raise  # existing exception handlers catch it → 502
    result = await fallback.generate(...)
    used_fallback = True

headers = {"X-Request-ID": request_id}
if used_fallback:
    headers["X-Fallback"] = "true"
    if isinstance(result, dict):
        result["fallback"] = True

if stream:
    return StreamingResponse(result, media_type="text/event-stream", headers=headers)
return JSONResponse(result, headers=headers)
```

**Changes to `config.py`:**
- `from_config()` reads `fallback_backend` from YAML
- `get_fallback()` returns the fallback backend instance (currently returns `None`)

**No changes to `gateway.py` or backend classes.**

**Key rules:**
- No fallback configured → errors pass through as today (502)
- Only one retry — no cascading
- Non-streaming: client sees `"fallback": true` in body + `X-Fallback: true` header
- Streaming: client sees `X-Fallback: true` header only

**Done when:** Four test scenarios pass:
1. Primary down + fallback configured (non-streaming) → 200 with `"fallback": true` in body + `X-Fallback` header
2. Primary down + fallback configured (streaming) → 200 with `X-Fallback` header
3. Primary down + no fallback → 502
4. Primary healthy → normal response, no fallback signals

---

## Step 7 — VllmBackend (Issue #12)

**Goal:** Third backend type proving extensibility. Subclasses `RemoteBackend`.

**New file:** `backends/vllm.py`

**What's different from RemoteBackend:**
- `info()` returns `"type": "vllm"` + vLLM-specific metadata
- Optional `/health` endpoint check
- Config: `type: vllm` with same `url` field

**Config example:**
```yaml
backends:
  vllm-llama:
    type: vllm
    url: http://localhost:8000
```

**Done when:** Adding vLLM required zero changes to `app.py` or the handler — just the class file + config entry. Shows up in `/v1/models` and `/v1/backends`.

---

## Verification (After Each Step)

```bash
uv run python test_gateway.py
```

Manual smoke tests (from Step 3 onward):
```bash
# Route to echo backend explicitly
curl -s localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}], "model":"echo"}' | jq .backend

# Default backend (no model specified)
curl -s localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}' | jq .backend

# List all backends
curl -s localhost:8080/v1/backends | jq .

# List all models
curl -s localhost:8080/v1/models | jq .data[].id
```
